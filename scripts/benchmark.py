"""Read-only timings; public result contains no SQL literals or patient records."""
import json
from pathlib import Path
from financial.config import ROOT,Settings
from financial.db import Database

db=Database(Settings.from_env().pgweb_url)
queries={
 'claim_key_lookup':"SELECT id FROM eclaim.claims WHERE id=(SELECT min(id) FROM eclaim.claims)",
 'rep_round_lookup':"SELECT id FROM reporting.rep_current WHERE claim_id=(SELECT min(id) FROM eclaim.claims)",
 'stm_claim_aggregate':"SELECT sum(net_amount),count(*) FROM reporting.stm_current WHERE claim_id=(SELECT min(id) FROM eclaim.claims)",
 'monthly_aggregate':"SELECT month,sum(statement_amount) FROM reporting.monthly_totals WHERE hcode='10929' AND basis='service' GROUP BY month",
 'his_encounter_page':"SELECT id FROM his.cases WHERE snapshot_id=(SELECT id FROM his.snapshots WHERE status IN ('ready','partial') ORDER BY completed_at DESC LIMIT 1) ORDER BY id LIMIT 50"
}
results=[]
for name,sql in queries.items():
    result=db.scalar('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+sql)
    if isinstance(result,str):result=json.loads(result)
    plan=result[0];root=plan['Plan']
    results.append({'query':name,'execution_ms':plan['Execution Time'],'planning_ms':plan['Planning Time'],'shared_hit_blocks':root.get('Shared Hit Blocks',0),'shared_read_blocks':root.get('Shared Read Blocks',0),'actual_rows':root['Actual Rows']})
report={'method':'EXPLAIN (ANALYZE, BUFFERS)','results':results,'his_certified':False,'limitation':'No complete live HIS encounter dataset available; claim/statement tests use existing corpus. Re-measure after HIS and full REP import.'}
(ROOT/'docs/PERFORMANCE_RESULT.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
