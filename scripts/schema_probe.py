from financial.config import Settings
from financial.db import Database

db=Database(Settings.from_env().pgweb_url)
for table in ('stm_claims','rep_claims','rep_instrument_items'):
    print(table,db.rows("SELECT column_name,is_nullable,column_default FROM information_schema.columns WHERE table_schema='eclaim' AND table_name='"+table+"' ORDER BY ordinal_position"))
