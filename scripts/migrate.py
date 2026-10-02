from financial.config import Settings
from financial.db import Database

if __name__=='__main__':
    settings=Settings.from_env()
    if settings.mode!='live':raise SystemExit('Migration requires live mode')
    Database(settings.pgweb_url).migrate()
    print('Financial schema 0.1.0 installed')
