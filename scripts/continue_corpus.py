"""Foreground CLI retry runner; uses the original checkpoint and bounded batches."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project',type=Path,required=True);args=parser.parse_args()
    project=args.project.resolve()
    if not (project/'repstm/cli.py').is_file():raise ValueError('IMPORT_PROJECT_MISSING')
    reports=project/'reports';reports.mkdir(exist_ok=True)
    attempt=0
    while not (reports/'stop_corpus').exists():
        attempt+=1
        with (reports/'rep_corpus_active.log').open('a',encoding='utf-8') as log:
            result=subprocess.run([sys.executable,'-m','repstm.cli','resume','--source','rep','--no-refresh'],cwd=project,stdout=log,stderr=log,env=os.environ.copy())
        print(json.dumps({'phase':'import_attempt','attempt':attempt,'exit_code':result.returncode}),flush=True)
        if result.returncode==0:break
        # A deterministic mapping/schema error needs review; retry only gateway failures.
        tail=(reports/'rep_corpus_active.log').read_text(encoding='utf-8')[-3000:]
        if 'PGWEB_UNAVAILABLE' not in tail:raise SystemExit('CORPUS_REQUIRES_REVIEW')
        time.sleep(30)
    else:return
    with (reports/'rep_corpus_finalize.log').open('a',encoding='utf-8') as log:
        status=subprocess.run([sys.executable,'-m','repstm.cli','verify','--refresh','--report',str(reports/'full_corpus_verification.json')],cwd=project,stdout=log,stderr=log).returncode
    print(json.dumps({'phase':'verification','exit_code':status,'report':'reports/full_corpus_verification.json'}),flush=True)
    return status

if __name__=='__main__':raise SystemExit(main())
