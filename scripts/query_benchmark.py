"""Explain actual repository queries, emitting numeric/node metrics only.

Run after the synthetic load fixture. Never export plans, predicates or row
values, and never invoke mutating refresh EXPLAIN against a hospital database.
"""
import json
from datetime import date
from pathlib import Path
import os


def run(db,snapshot,start,end):
    from financial.repository import Repository
    from financial.config import Settings
    repo=Repository(Settings(pgweb_url='synthetic'))
    queries=[]
    class Recorder:
        transport=db.transport
        def rows(self,sql):queries.append(sql);return db.rows(sql)
        def scalar(self,sql):queries.append(sql);return db.scalar(sql)
        def json(self,sql):queries.append(sql);return db.json(sql)
        def report_json(self,sql):queries.append(sql);return db.report_json(sql)
    recorder=Recorder();repo.db=lambda:recorder
    batches=[]
    repo.overview(start,end,snapshot);batches.append(('overview',list(queries)));queries.clear()
    page=repo.cases(start,end,snapshot,search='0000');batches.append(('cases',list(queries)));queries.clear()
    if page['items']:
        repo.case(page['items'][0]['id']);batches.append(('detail',list(queries)));queries.clear()
    # Mutating benchmark only on disposable infrastructure. Bound work remains
    # equivalent and subsequent refresh drains the surviving durable queue.
    assert db.scalar('SELECT current_database()')=='stmrep_test'
    db.execute('INSERT INTO his.dirty_claim_links(claim_id) SELECT id FROM eclaim.claims ORDER BY id LIMIT 200 ON CONFLICT DO NOTHING')
    batches.append(('refresh',['SELECT his.refresh_links(200)']))
    result=[]
    for label,sqls in batches:
        for index,sql in enumerate(sqls):
            from financial.db import literal
            parsed=db.json(f'SELECT analytics.explain_query({literal(sql)})')
            if isinstance(parsed,str):parsed=json.loads(parsed)
            plan=parsed[0];root=plan['Plan'];nodes=[]
            def walk(node):
                nodes.append({'node':node['Node Type'],'rows':node['Actual Rows'],'loops':node['Actual Loops']})
                for child in node.get('Plans',[]):walk(child)
            walk(root)
            result.append({'operation':label,'statement':index+1,'execution_ms':plan['Execution Time'],
                'planning_ms':plan['Planning Time'],'shared_hit_blocks':root.get('Shared Hit Blocks',0),
                'shared_read_blocks':root.get('Shared Read Blocks',0),'temp_written_blocks':root.get('Temp Written Blocks',0),
                'nodes':nodes})
    report={'fixture':'synthetic_only','method':'EXPLAIN (ANALYZE, BUFFERS)','queries':result,'his_certified':False}
    out=Path(__file__).resolve().parents[1]/'.ci';out.mkdir(exist_ok=True)
    (out/'query-benchmark.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    from scripts.performance_check import test_database,SNAPSHOT
    os.environ['PGWEB_MIN_INTERVAL']='0'
    with test_database('http://127.0.0.1:18831') as db:
        report=run(db,SNAPSHOT,date(2026,1,1),date(2026,1,31))
    print(json.dumps({'fixture':report['fixture'],'queries':len(report['queries']),'status':'passed'}))
