"""Extract only literal item catalogue rows; never execute external SQL."""
import argparse
import json
from pathlib import Path
import re
from financial.config import ROOT,Settings
from financial.db import Database,json_sql

def main():
    p=argparse.ArgumentParser();p.add_argument('sql',type=Path);args=p.parse_args()
    source=args.sql.read_text(encoding='utf-8-sig')
    pattern=r"\('([0-9]+)',\s*'([^']*)',\s*'([^']*)',\s*'((?:[^']|'')*)',\s*(NULL|[0-9.]+),\s*(?:NULL|[0-9.]+),\s*(?:NULL|'(?:[^']|'')*')\)"
    rows=[{'icode':m[0],'billcode':m[1],'category':m[2],'item_name':m[3].replace("''","'"),'legacy_rate':None if m[4]=='NULL' else m[4]} for m in re.findall(pattern,source)]
    if not rows:raise ValueError('CATALOG_LITERAL_ROWS_NOT_FOUND')
    (ROOT/'financial/instrument_catalog.json').write_text(json.dumps({'source_ref':'ipd_instrument_billcode.sql / organ_สมบูรณ์_2566.xlsx','source_year':2566,'verification':'observed_only','rates_usable':False,'items':rows},ensure_ascii=False,indent=2),encoding='utf-8')
    sql=f"INSERT INTO followup.instrument_catalog(icode,billcode,item_name,category,legacy_rate,source_ref,source_year,verification) SELECT x.icode,x.billcode,x.item_name,x.category,x.legacy_rate::numeric,'ipd_instrument_billcode.sql / organ_สมบูรณ์_2566.xlsx',2566,'observed_only' FROM jsonb_to_recordset({json_sql(rows)}) AS x(icode text,billcode text,item_name text,category text,legacy_rate text) ON CONFLICT(icode,source_ref) DO NOTHING"
    Database(Settings.from_env().pgweb_url).execute(sql)
    print(f'Imported {len(rows)} observed catalogue items; rates are not approved for claims')

if __name__=='__main__':main()
