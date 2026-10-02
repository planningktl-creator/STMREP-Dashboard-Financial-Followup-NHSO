"""Inspect repository publishing candidates; report paths, never secret values."""
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parent.parent


def main():
    names=subprocess.check_output(['git','ls-files','--cached','--others','--exclude-standard','-z'],cwd=ROOT).decode().split('\0')
    failures=[];names=sorted(set(filter(None,names)))
    private=[]
    env=ROOT/'.env'
    if env.exists():
        for line in env.read_text(encoding='utf-8-sig').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key,value=line.split('=',1)
                if key in ('PGWEB_URL','BMS_ALLOWED_HOSTS') and len(value.strip())>12:
                    private.append(value.strip().strip('"'))
    for name in names:
        p=Path(name)
        if (p.parts[0] in ('.data','state','archive','reports','output','.ci') or p.suffix.lower() in ('.xls','.xlsx','.csv','.sqlite','.sqlite3','.log') or name=='.env'):
            failures.append(name);continue
        try:content=(ROOT/p).read_text(encoding='utf-8')
        except UnicodeError:continue
        real_urls=re.findall(r'postgres(?:ql)?://[^\s"\']+:[^\s"\']+@[^\s"\']+',content)
        if name=='deploy/compose.test.yaml':real_urls=[url for url in real_urls if not url.split('://',1)[1].startswith('synthetic:synthetic-test-only@postgres:')]
        if real_urls or re.search(r'gh[opsu]_[A-Za-z0-9]{20,}',content) or re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',content) or any(value in content for value in private):
            failures.append(name)
    print(json.dumps({'status':'failed' if failures else 'passed','files':len(names),'flagged_paths':failures}))
    if failures:raise SystemExit(1)


if __name__=='__main__':main()
