from __future__ import annotations

import argparse
import base64
import collections
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import uuid
from xlrd.biffh import XLRDError

from .db import Pgweb, body_size, MAX_BODY
from .parser import parse_file, canonical, digest, VERSION
from .schema import schema_sql

ROOT=Path(__file__).resolve().parent.parent
DEFAULT_URL=os.getenv('PGWEB_URL','')
DEFAULT_STM=Path(os.getenv('STM_DIR',str(ROOT/'data'/'incoming'/'stm')))
DEFAULT_REP=Path(os.getenv('REP_DIR',str(ROOT/'data'/'incoming'/'rep')))


def emit(data):
    print(canonical(data),flush=True)


class State:
    def __init__(self,path):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
        CREATE TABLE IF NOT EXISTS batches(id TEXT PRIMARY KEY,payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS files(path TEXT NOT NULL,sha256 TEXT NOT NULL,document_key TEXT,status TEXT NOT NULL,stats TEXT NOT NULL,PRIMARY KEY(path,sha256));
        CREATE TABLE IF NOT EXISTS progress(document_key TEXT,sheet_index INTEGER,kind TEXT,last_row INTEGER,PRIMARY KEY(document_key,sheet_index,kind));
        """)

    def target(self,identity):
        existing=self.db.execute("SELECT value FROM meta WHERE key='target'").fetchone()
        if existing and existing[0]!=identity:
            raise RuntimeError("DATABASE_IDENTITY_CHANGED: choose a new --state path")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('target',?)",(identity,));self.db.commit()

    def done(self,path,sha,retry_blocked=False):
        states="('done')" if retry_blocked else "('done','blocked')"
        return self.db.execute(f"SELECT 1 FROM files WHERE path=? AND sha256=? AND status IN {states}",(str(path),sha)).fetchone() is not None

    def ready_document(self,key):
        return self.db.execute("SELECT 1 FROM files WHERE document_key=? AND status='done'",(key,)).fetchone() is not None

    def parsed(self,path,sha,parsed):
        stats={"rows":parsed["document"]["expected_counts"],"issues":len(parsed["issues"]),"errors":sum(i["severity"]=="error" for i in parsed["issues"])}
        self.db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,'parsed',?)",(str(path),sha,parsed["document"]["key"],canonical(stats)));self.db.commit()

    def queue(self,ident,payload):
        self.db.execute("INSERT INTO batches(id,payload,created_at) VALUES(?,?,?)",(ident,canonical(payload),time.time()));self.db.commit()

    def acknowledge(self,ident,payload,result):
        for g in payload.get('groups',[]):
            if g['rows']:
                col=g['columns'].index('source_row');last=max(r[col] for r in g['rows'])
                self.db.execute('INSERT INTO progress VALUES(?,?,?,?) ON CONFLICT(document_key,sheet_index,kind) DO UPDATE SET last_row=max(last_row,excluded.last_row)',
                                (g['document_key'],g['sheet_index'],g['kind'],last))
        for marker in payload.get("_done_files",[]):
            doc=self.db.execute('SELECT document_key FROM files WHERE path=? AND sha256=?',(marker['path'],marker['sha256'])).fetchone()
            remote=result.get('document_statuses',{}).get(doc[0]) if doc else None
            status="blocked" if marker["errors"] or remote in ('blocked','ambiguous') else "done"
            self.db.execute("UPDATE files SET status=? WHERE path=? AND sha256=?",(status,marker["path"],marker["sha256"]))
        # Keep IDs, hashes and metrics after commit; full patient payloads are
        # needed locally only until the server acknowledges the exact batch.
        receipt={'payload_sha256':hashlib.sha256(canonical(payload).encode()).hexdigest(),
                 'bytes':body_size(ident,payload),'records':sum(len(g['rows']) for g in payload.get('groups',[])),
                 'result':result}
        self.db.execute("UPDATE batches SET status='committed',payload=? WHERE id=?",(canonical(receipt),ident));self.db.commit()

    def pending(self):
        return self.db.execute("SELECT id,payload FROM batches WHERE status='pending' ORDER BY created_at")

    def checkpoint(self,key,sheet,kind):
        row=self.db.execute('SELECT last_row FROM progress WHERE document_key=? AND sheet_index=? AND kind=?',(key,sheet,kind)).fetchone()
        return row[0] if row else 0

    def sync_checkpoint(self,db,key):
        from .parser import KINDS
        if not re.fullmatch('[0-9a-f]{64}',key):raise ValueError('Invalid fingerprint')
        sql=' UNION ALL '.join(f"SELECT s.sheet_index,'{kind}',max(t.source_row) FROM {'ingest' if kind=='unmapped_rows' else 'eclaim'}.{kind} t JOIN ingest.sheets s ON s.id=t.sheet_id JOIN ingest.documents d ON d.id=t.document_id WHERE d.fingerprint='{key}' GROUP BY s.sheet_index" for kind in KINDS)
        for sheet,kind,last in db.query(sql)['rows']:
            self.db.execute('INSERT INTO progress VALUES(?,?,?,?) ON CONFLICT(document_key,sheet_index,kind) DO UPDATE SET last_row=max(last_row,excluded.last_row)',(key,sheet,kind,last))
        self.db.commit()

    def seed_remote(self,db):
        rows=db.query("SELECT f.source_path,f.sha256,d.fingerprint,d.status,d.expected_counts::text,f.archive_path FROM ingest.files f JOIN ingest.documents d ON d.id=f.document_id WHERE d.status IN ('ready','blocked','ambiguous')")['rows']
        for path,sha,key,status,counts,arc in rows:
            if not arc or not Path(arc).exists():continue
            stats=canonical({'rows':json.loads(counts),'errors':int(status!='ready'),'issues':0})
            self.db.execute("INSERT INTO files VALUES(?,?,?,?,?) ON CONFLICT(path,sha256) DO UPDATE SET document_key=excluded.document_key,status=excluded.status,stats=excluded.stats",
                            (path,sha,key,'done' if status=='ready' else 'blocked',stats))
        self.db.commit()


class Packer:
    def __init__(self,db,state,max_records=500,max_bytes=MAX_BODY,run_id=None):
        self.db,self.state=db,state
        self.max_records=min(max_records,500);self.max_bytes=min(max_bytes,MAX_BODY)
        self.run_id=run_id or str(uuid.uuid4());self.total_rows=0;self.batch_count=0
        self.reset()

    def reset(self):
        self.batch_id=str(uuid.uuid4())
        self.payload={"run_id":self.run_id,"documents":[],"files":[],"sheets":[],"issues":[],"groups":[],"complete":[],"_done_files":[]}
        self.count=0
        self.estimated=body_size(self.batch_id,self.payload)

    def flush(self):
        if not any(self.payload[k] for k in self.payload if k!='run_id'):return
        if body_size(self.batch_id,self.payload)>self.max_bytes:
            raise ValueError('BATCH_SIZE_INVARIANT_FAILED')
        self.state.queue(self.batch_id,self.payload)
        result=self.db.apply(self.batch_id,self.payload)
        self.state.acknowledge(self.batch_id,self.payload,result)
        self.batch_count+=1;self.total_rows+=result.get("inserted",0)
        if self.batch_count%20==0:emit({"phase":"upload","batches":self.batch_count,"inserted":self.total_rows})
        self.reset()

    def add(self,key,value):
        self.payload[key].append(value)
        if body_size(self.batch_id,self.payload)>self.max_bytes:
            self.payload[key].pop();self.flush();self.payload[key].append(value)
            if body_size(self.batch_id,self.payload)>self.max_bytes:raise ValueError("SINGLE_METADATA_EXCEEDS_BATCH_LIMIT")
        self.estimated=body_size(self.batch_id,self.payload)

    def row(self,group,row):
        # Append to the last contiguous group, rather than repeating provenance.
        def append():
            g=self.payload["groups"][-1] if self.payload["groups"] else None
            if not g or any(g[k]!=group[k] for k in ('document_key','sheet_index','kind')):
                g={**group,"rows":[]};self.payload["groups"].append(g)
            g["rows"].append(row)
            return g
        raw=canonical(row).encode('utf-8')
        # Bound URL-encoded base64 at each of the three possible byte alignments.
        # Avoid serializing the entire growing batch for every individual row.
        costs=[]
        for offset in (0,1,2):
            encoded=base64.b64encode(b'xx'[:offset]+raw)
            costs.append(len(encoded)+2*sum(encoded.count(c) for c in (b'+',b'/',b'='))+32)
        header_cost=len(canonical({**group,'rows':[]}).encode('utf-8'))*4+32
        last=self.payload['groups'][-1] if self.payload['groups'] else None
        new_group=not last or any(last[k]!=group[k] for k in ('document_key','sheet_index','kind'))
        cost=max(costs)+(header_cost if new_group else 0)
        if self.count>=self.max_records or self.estimated+cost>self.max_bytes:
            self.flush();cost=max(costs)+header_cost
        append();self.count+=1;self.estimated+=cost
        if cost>self.max_bytes and body_size(self.batch_id,self.payload)>self.max_bytes:
            raise ValueError('SINGLE_ROW_EXCEEDS_BATCH_LIMIT')


def candidates(args):
    ps=[]
    if args.source in ('stm','both'):ps.extend(args.stm_dir.glob('STM_10929_*.xls'))
    if args.source in ('rep','both'):ps.extend(args.rep_dir.glob('eclaim_*.xls'))
    ps=sorted(ps,key=lambda p:(not p.name.startswith('STM_'),p.name))
    if args.file:ps=[Path(p) for p in args.file]
    if args.representative:
        families=collections.defaultdict(list)
        for p in ps:
            kind=re.sub(r'_\d{8}.*','',re.sub(r'^eclaim_\d+_','',p.name)) if p.name.startswith('eclaim_') else p.name.split('_')[2][:5]
            families[kind].append(p)
        ps=list(dict.fromkeys(p for fs in families.values() for p in (min(fs),max(fs),max(fs,key=lambda x:x.stat().st_size))))
    if args.limit:ps=ps[:args.limit]
    return ps


def file_sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def archive(path,sha,root):
    dest=root/sha[:2]/(sha+'.xls');dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():
        temp=dest.with_suffix('.partial');shutil.copyfile(path,temp)
        if file_sha(temp)!=sha:raise RuntimeError("SOURCE_CHANGED_DURING_ARCHIVE")
        temp.replace(dest)
    elif file_sha(dest)!=sha:raise RuntimeError('ARCHIVE_HASH_MISMATCH')
    return str(dest.resolve())


def inspect_files(args):
    counts=collections.Counter();layouts={};errors=[];docs={};aliases=[];totals=collections.Counter();start=time.monotonic();issue_details=[]
    paths=candidates(args)
    for i,path in enumerate(paths,1):
        try:
            parsed=parse_file(path,profile_only=args.fast,allow_new_layouts=args.allow_new_layouts)
            fp=parsed['document']['key'];logical=parsed['document']['logical_key']
            counts.update(parsed['document']['expected_counts'])
            for s in parsed['sheets']:layouts[s['layout_id']]=s['layout']
            issues=collections.Counter(x['code'] for x in parsed['issues']);totals.update(issues)
            if parsed['issues']:issue_details.append({'file':path.name,'issues':parsed['issues']})
            if fp in docs:aliases.append({'file':path.name,'canonical_file':docs[fp]['file'],'rows':parsed['document']['expected_counts']})
            else:docs[fp]={'file':path.name,'logical_key':logical,'rows':parsed['document']['expected_counts'],'issues':dict(issues)}
            if any(x['severity']=='error' for x in parsed['issues']):errors.append({'file':path.name,'codes':dict(issues)})
        except Exception as exc:
            errors.append({'file':path.name,'codes':{'PARSE_FAILED':1},'exception_type':type(exc).__name__})
        if i%50==0:emit({'phase':'inspect','files':i,'total':len(paths),'rows':dict(counts)})
    report={'files':len(paths),'rows_before_dedup':dict(counts),'logical_documents':len(docs),'aliases':aliases,
            'canonical_rows':dict(sum((collections.Counter(d['rows']) for d in docs.values()),collections.Counter())),
            'layout_count':len(layouts),'layouts':layouts,'issue_counts':dict(totals),'blocked_files':errors,
            'issue_details':issue_details,'mapping_version':VERSION,
            'fingerprint_mode':'disabled_financial_profile' if args.fast else 'full_content',
            'elapsed_seconds':round(time.monotonic()-start,2)}
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(canonical(report),encoding='utf-8')
    emit({k:v for k,v in report.items() if k not in ('layouts','blocked_files','aliases','issue_details')})
    emit({'report':str(args.report.resolve()),'blocked_files':len(errors),'aliases':len(aliases)})
    return 1 if errors else 0


def import_files(args):
    if args.dry_run:return inspect_files(args)
    db=Pgweb(args.pgweb_url);state=State(args.state);state.target(db.identity())
    for ident,payload_json in state.pending().fetchall():
        payload=json.loads(payload_json);result=db.apply(ident,payload);state.acknowledge(ident,payload,result)
        emit({'phase':'resume','batch_id':ident,'inserted':result.get('inserted',0)})
    state.seed_remote(db)
    pack=Packer(db,state,args.batch_records,args.batch_bytes)
    db.query(f"INSERT INTO ingest.runs(id,metadata) VALUES('{pack.run_id}'::uuid,jsonb_build_object('source','{args.source}','mapper_version','{VERSION}')) ON CONFLICT DO NOTHING")
    paths=candidates(args);processed=skipped=0;start=time.monotonic()
    manifest=open(args.state.parent/'import_manifest.jsonl','a',encoding='utf-8')
    try:
        for i,path in enumerate(paths,1):
            sha=file_sha(path)
            if state.done(path,sha,args.retry_blocked):skipped+=1;continue
            arc=archive(path,sha,args.archive_dir)
            try:parsed=parse_file(path,content_path=arc)
            except (ValueError,OSError,XLRDError) as exc:
                # The archive preserves the workbook even if it cannot be read.
                source='STM' if path.name.startswith('STM_') else 'REP';parts=path.stem.split('_');pt='IP' if parts[2].startswith('IP') else 'OP'
                logical=':'.join([source,parts[1],pt,path.stem]);fp=digest({'logical_key':logical,'sha256':sha})
                parsed={'document':{'key':fp,'logical_key':logical,'document_ref':path.stem,'source':source,'hcode':parts[1],
                         'payer_family':'UNKNOWN','patient_type':pt,'reported_at':None,'statement_month':None,'expected_counts':{}},
                        'sheets':[],'groups':[],'issues':[{'code':'WORKBOOK_PARSE_FAILED','severity':'error','detail':{'exception_type':type(exc).__name__}}]}
            was_partial=state.db.execute("SELECT 1 FROM files WHERE path=? AND sha256=? AND status='parsed'",(str(path),sha)).fetchone()
            doc=parsed['document'];key=doc['key'];state.parsed(path,sha,parsed)
            duplicate=state.ready_document(key)
            # Read the remote committed prefix as well. This supports moving a
            # checkpoint file and upgrading from file-level checkpoints.
            if was_partial and not duplicate:state.sync_checkpoint(db,key)
            pack.add('documents',doc)
            pack.add('files',{'sha256':sha,'source_path':str(path.resolve()),'filename':path.name,'byte_size':Path(arc).stat().st_size,
                              'archive_path':arc,'document_key':key,'reported_at':doc['reported_at']})
            if not duplicate:
                for sheet in parsed['sheets']:pack.add('sheets',{**sheet,'document_key':key})
                for issue in parsed['issues']:pack.add('issues',{**issue,'document_key':key})
                for g in parsed['groups']:
                    header={k:v for k,v in g.items() if k!='rows'};header['document_key']=key
                    last=state.checkpoint(key,g['sheet_index'],g['kind']);source_col=g['columns'].index('source_row')
                    for row in g['rows']:
                        if row[source_col]>last:pack.row(header,row)
            pack.add('complete',key)
            pack.add('_done_files',{'path':str(path),'sha256':sha,'errors':sum(x['severity']=='error' for x in parsed['issues'])})
            manifest.write(canonical({'file':path.name,'sha256':sha,'document_key':key,'rows':doc['expected_counts'],
                                      'issues':collections.Counter(x['code'] for x in parsed['issues'])})+'\n');manifest.flush()
            # Only the final bounded batch should retain rows between files.
            parsed=None;g=None
            processed+=1
            if i%20==0:emit({'phase':'files','processed':processed,'skipped':skipped,'position':i,'total':len(paths),'elapsed_seconds':round(time.monotonic()-start,1)})
        pack.flush()
        if not args.no_refresh:db.refresh(emit)
        db.query(f"UPDATE ingest.runs SET status='complete',finished_at=now() WHERE id='{pack.run_id}'::uuid")
        elapsed=time.monotonic()-start
        metrics={'phase':'complete','processed':processed,'skipped':skipped,'inserted':pack.total_rows,
                 'requests':db.request_count,'request_seconds':round(db.request_seconds,2),
                 'elapsed_seconds':round(elapsed,1),'inserted_records_per_second':round(pack.total_rows/max(elapsed,0.001),2)}
        db.query(f"UPDATE ingest.runs SET metadata=convert_from(decode('{base64.b64encode(canonical(metrics).encode()).decode()}','base64'),'UTF8')::jsonb WHERE id='{pack.run_id}'::uuid")
        emit(metrics)
    except BaseException as exc:
        try:db.query(f"UPDATE ingest.runs SET status='failed',finished_at=now(),metadata=metadata||jsonb_build_object('error_type','{type(exc).__name__}') WHERE id='{pack.run_id}'::uuid",retry=False)
        except Exception:pass
        raise
    finally:manifest.close()
    return 0


def verify(args):
    db=Pgweb(args.pgweb_url)
    if args.refresh:
        db.refresh(emit)
        if db.scalar("SELECT to_regprocedure('his.rebuild_links(uuid)') IS NOT NULL"):
            for snapshot, in db.query("SELECT id::text FROM his.snapshots WHERE status IN ('ready','partial') ORDER BY completed_at")['rows']:
                db.scalar(f"SELECT his.rebuild_links('{uuid.UUID(snapshot)}'::uuid)")
            emit({'phase':'his_claim_links_refreshed'})
    report={}
    report['documents']=db.query("SELECT source,status,is_current,count(*) FROM ingest.documents GROUP BY 1,2,3 ORDER BY 1,2,3")
    report['rows']=db.query("SELECT 'rep_claims' AS kind,count(*) AS total FROM eclaim.rep_claims UNION ALL SELECT 'stm_claims',count(*) FROM eclaim.stm_claims UNION ALL SELECT 'rep_drug_items',count(*) FROM eclaim.rep_drug_items UNION ALL SELECT 'rep_instrument_items',count(*) FROM eclaim.rep_instrument_items UNION ALL SELECT 'rep_denial_items',count(*) FROM eclaim.rep_denial_items UNION ALL SELECT 'rep_zero_pay_items',count(*) FROM eclaim.rep_zero_pay_items")
    report['issues']=db.query("SELECT severity,code,count(*) FROM ingest.issues GROUP BY 1,2 ORDER BY 1,2")
    report['reconciliation']=db.query("SELECT status,count(*) FROM reporting.reconciliation_matches GROUP BY 1 ORDER BY 1")
    report['dirty']=db.query("SELECT (SELECT count(*) FROM reporting.dirty_claims),(SELECT count(*) FROM reporting.dirty_months)")
    report['storage']=db.query("SELECT pg_database_size(current_database()),pg_size_pretty(pg_database_size(current_database()))")
    report['stm_baseline']=db.query("SELECT count(*) AS active_rows,count(*) FILTER(WHERE net_amount<0) AS negative_rows,sum(compensation_amount) AS gross_statement,sum(net_amount) AS net_statement FROM reporting.stm_current")
    report['source_baseline']=db.query("SELECT d.source,count(*) AS files,count(DISTINCT d.id) AS canonical_documents,sum(coalesce((d.expected_counts->>CASE WHEN d.source='STM' THEN 'stm_claims' ELSE 'rep_claims' END)::bigint,0)) AS physical_source_claim_rows FROM ingest.files f JOIN ingest.documents d ON d.id=f.document_id GROUP BY 1")
    report['missing_dates']=db.query("SELECT 'REP' AS source,count(*) FROM reporting.rep_current WHERE service_date IS NULL UNION ALL SELECT 'STM',count(*) FROM reporting.stm_current WHERE service_date IS NULL")
    # Partial batch/blocked documents and same-month file aliases are visible here.
    report['files']=db.query("SELECT count(*) AS files,count(DISTINCT document_id) AS documents FROM ingest.files")
    archives=db.query('SELECT DISTINCT sha256,archive_path FROM ingest.files')['rows']
    report['archive_integrity']={'checked':len(archives),'problems':[]}
    for sha,path in archives:
        problem='missing' if not path or not Path(path).is_file() else 'hash_mismatch' if file_sha(Path(path))!=sha else None
        if problem:report['archive_integrity']['problems'].append({'sha256':sha,'problem':problem})
    report['integrity']=db.query("SELECT (SELECT count(*) FROM eclaim.rep_claims WHERE claim_id IS NULL) AS rep_without_identity,(SELECT count(*) FROM eclaim.stm_claims WHERE claim_id IS NULL) AS stm_without_identity,(SELECT count(*) FROM reporting.reconciliation_matches m JOIN reporting.rep_current r ON r.id=m.rep_claim_id JOIN reporting.stm_current s ON s.id=m.stm_claim_id WHERE r.claim_id<>s.claim_id OR r.rep_no<>s.rep_no) AS bad_matches")
    from .parser import KINDS
    count_sql=' UNION ALL '.join(f"SELECT document_id,'{kind}' AS kind,count(*) AS actual FROM {'ingest' if kind=='unmapped_rows' else 'eclaim'}.{kind} GROUP BY document_id" for kind in KINDS)
    report['row_count_mismatches']=db.query("WITH actual AS ("+count_sql+") SELECT d.id,e.key AS kind,e.value::text::bigint AS expected,coalesce(a.actual,0) AS actual FROM ingest.documents d CROSS JOIN LATERAL jsonb_each(d.expected_counts) e LEFT JOIN actual a ON a.document_id=d.id AND a.kind=e.key WHERE d.status<>'loading' AND coalesce(a.actual,0)<>e.value::text::bigint")
    report['revision_ties']=db.query("SELECT logical_key,count(*) AS versions FROM ingest.documents WHERE status='ambiguous' GROUP BY 1")
    report['latest_claim_ties']=db.query("WITH r AS (SELECT r.claim_id,dense_rank() OVER(PARTITION BY r.claim_id ORDER BY d.reported_at DESC NULLS LAST) AS rank FROM reporting.rep_current r JOIN ingest.documents d ON d.id=r.document_id WHERE r.claim_id IS NOT NULL) SELECT count(*) AS ambiguous_latest_claims FROM (SELECT claim_id FROM r WHERE rank=1 GROUP BY claim_id HAVING count(*)>1) t")
    report['summary_differences']=db.query("SELECT f.filename,i.sheet_index+1 AS excel_sheet_number,i.source_row,i.code,i.detail FROM ingest.issues i JOIN LATERAL (SELECT filename FROM ingest.files WHERE document_id=i.document_id ORDER BY id LIMIT 1) f ON true WHERE i.code LIKE '%SUMMARY%MISMATCH' ORDER BY f.filename,i.sheet_index,i.source_row")
    report['completeness']={'stm_expected_files':178,'stm_expected_source_rows':649497,'stm_expected_canonical_rows':645083,
                            'rep_expected_files':13936,'note':'Source baseline numbers apply to the supplied corpus; compare files imported separately from files inspected.'}
    actual_files={r[0]:r[1] for r in report['source_baseline']['rows']}
    report['completeness']['all_corpus_files_imported']=actual_files.get('STM',0)==178 and actual_files.get('REP',0)==13936
    report['import_status']='needs_review' if any(r[1] in ('loading','blocked','ambiguous') for r in report['documents']['rows']) else 'complete_for_registered_files'
    report['reporting_status']='refresh_required' if any(report['dirty']['rows'][0]) else 'ready'
    report['check_status']='failed' if report['row_count_mismatches']['rows'] or any(report['integrity']['rows'][0]) or report['archive_integrity']['problems'] else 'passed'
    args.report.parent.mkdir(parents=True,exist_ok=True);args.report.write_text(canonical(report),encoding='utf-8')
    emit({k:v for k,v in report.items() if k!='summary_differences'});emit({'report':str(args.report.resolve()),'summary_difference_rows':len(report['summary_differences']['rows'])})
    return 1 if report['check_status']=='failed' else 0


def main(argv=None):
    if hasattr(sys.stdout,'reconfigure'):sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description='REP/STM immutable-history import and reconciliation')
    parser.add_argument('command',choices=['inspect','migrate','import','resume','verify','refresh','emit-schema'])
    parser.add_argument('--source',choices=['stm','rep','both'],default='both')
    parser.add_argument('--stm-dir',type=Path,default=DEFAULT_STM);parser.add_argument('--rep-dir',type=Path,default=DEFAULT_REP)
    parser.add_argument('--file',action='append');parser.add_argument('--limit',type=int)
    parser.add_argument('--representative',action='store_true',help='Profile oldest/newest/largest workbook for each report kind')
    parser.add_argument('--fast',action='store_true',help='Inspect financial mappings/counts without content fingerprint or raw-cell copies')
    parser.add_argument('--allow-new-layouts',action='store_true',help='Inspect proposed layouts; import always requires an approved fingerprint')
    parser.add_argument('--pgweb-url',default=os.getenv('PGWEB_URL',DEFAULT_URL))
    parser.add_argument('--state',type=Path,default=ROOT/'state'/'import_state.sqlite3')
    parser.add_argument('--archive-dir',type=Path,default=ROOT/'data'/'archive')
    parser.add_argument('--report',type=Path,default=ROOT/'reports'/'verification.json')
    parser.add_argument('--batch-records',type=int,default=500);parser.add_argument('--batch-bytes',type=int,default=MAX_BODY)
    parser.add_argument('--dry-run',action='store_true');parser.add_argument('--no-refresh',action='store_true');parser.add_argument('--refresh',action='store_true')
    parser.add_argument('--retry-blocked',action='store_true',help='Reparse locally blocked files after fixing a mapping or source')
    args=parser.parse_args(argv)
    if args.command in ('inspect',) or args.dry_run:return inspect_files(args)
    if args.command=='emit-schema':
        dest=ROOT/'migrations'/'001_schema.sql';dest.parent.mkdir(exist_ok=True);dest.write_text('DO $migration$ BEGIN\n'+schema_sql()+'\nEND $migration$;',encoding='utf-8');emit({'migration':str(dest)});return 0
    if args.command=='migrate':
        db=Pgweb(args.pgweb_url)
        db.query('DO $migration$ BEGIN\n'+schema_sql()+'\nEND $migration$;',retry=False)
        emit({'schema_version':db.scalar("SELECT version FROM ingest.schema_versions WHERE version='1.0.0'")});return 0
    if args.command in ('import','resume'):return import_files(args)
    if args.command=='refresh':Pgweb(args.pgweb_url).refresh(emit);return 0
    return verify(args)


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as exc:
        # Tracebacks can include payload values. Keep CLI logs to operational errors.
        emit({'error_type':type(exc).__name__,'error':str(exc)[:1200]});raise SystemExit(2)
