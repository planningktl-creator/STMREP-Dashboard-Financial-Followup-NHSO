from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_env(path: Path = ROOT / '.env') -> None:
    if path.is_file():
        for line in path.read_text(encoding='utf-8-sig').splitlines():
            if line.strip() and not line.lstrip().startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    mode: str = 'live'
    hospital: str = '10929'
    pgweb_url: str = ''
    paste_url: str = 'https://hosxp.net/phapi/PasteJSON'
    bms_hosts: tuple[str, ...] = ('hosxp.net',)
    origins: tuple[str, ...] = ('http://127.0.0.1:8000', 'http://localhost:8000')
    data_dir: Path = ROOT / '.data'
    cookie_secure: bool = True
    worker_enabled: bool = True
    cost_semantics: str = 'unverified'
    cost_review: str = ''
    max_file_bytes: int = 100 * 1024 * 1024
    max_upload_bytes: int = 300 * 1024 * 1024
    minimum_free_bytes: int = 256 * 1024 * 1024
    report_timeout: float = 90
    shutdown_timeout: float = 120

    @classmethod
    def from_env(cls):
        load_env()
        mode = os.getenv('APP_MODE', 'live')
        if mode not in ('live', 'demo'):
            raise ValueError('APP_MODE must be live or demo')
        cost = os.getenv('ITEM_COST_SEMANTICS', 'unverified')
        review = os.getenv('ITEM_COST_REVIEW_REFERENCE', '')
        if cost not in ('unverified', 'line', 'unit') or (cost != 'unverified' and not review):
            raise ValueError('A reviewed line/unit cost definition requires its review reference')
        return cls(mode=mode, hospital=os.getenv('HOSPITAL_CODE', '10929'),
                   pgweb_url=os.getenv('PGWEB_URL', ''), paste_url=os.getenv('BMS_PASTE_URL', cls.paste_url),
                   bms_hosts=tuple(x.strip().lower() for x in os.getenv('BMS_ALLOWED_HOSTS', 'hosxp.net').split(',') if x.strip()),
                   origins=tuple(x.strip() for x in os.getenv('APP_ORIGINS', 'http://127.0.0.1:8000,http://localhost:8000').split(',') if x.strip()),
                   data_dir=Path(os.getenv('DATA_DIR', str(ROOT / '.data'))).resolve(),
                   cookie_secure=os.getenv('COOKIE_SECURE', 'true').lower() == 'true',
                   worker_enabled=os.getenv('WORKER_ENABLED', 'true').lower() == 'true',
                   cost_semantics=cost, cost_review=review,
                   minimum_free_bytes=int(os.getenv('MINIMUM_FREE_BYTES', str(256 * 1024 * 1024))))
