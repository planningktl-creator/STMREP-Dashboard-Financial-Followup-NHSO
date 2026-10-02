"""Check registry columns against operator-supplied schema metadata, without HIS rows."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from financial.config import ROOT
from financial.queries import DATASETS


def validate(metadata):
    columns={}
    for row in metadata:
        columns.setdefault(row['ชื่อตาราง'],{})[row['ชื่อคอลัมน์']]=row
    results=[]
    for dataset,(table,pk,fields,_) in DATASETS.items():
        available=columns.get(table,{})
        requested={re.split(r'::|\s+AS\s+',s.strip(),flags=re.I)[0] for s in fields.split(',')}|{pk}
        results.append({'dataset':dataset,'source_table':table,'source_key':pk,
                        'matches_metadata_pk':pk in available and available[pk]['เป็น Primary Key']=='YES',
                        'missing_columns':sorted(requested-set(available))})
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--hosxp',type=Path,required=True);args=parser.parse_args()
    raw=args.hosxp.read_bytes();results=validate(json.loads(raw.decode('utf-8-sig')))
    status='failed' if any(r['missing_columns'] for r in results) else 'passed'
    report={'status':status,'source_sha256':hashlib.sha256(raw).hexdigest(),
            'evidence':'Supplied schema metadata; not a live availability certification','datasets':results}
    (ROOT/'docs/HIS_SOURCE_METADATA_CHECK.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':status,'datasets':len(results),'missing_columns':sum(len(r['missing_columns']) for r in results)}))
    return int(status!='passed')


if __name__=='__main__':raise SystemExit(main())
