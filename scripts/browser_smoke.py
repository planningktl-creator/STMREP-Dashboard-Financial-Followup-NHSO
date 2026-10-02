"""Browser acceptance with synthetic Session transport; no real BMS requests."""
import json
import subprocess
import time
from pathlib import Path
import requests
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parent.parent
BASE='http://127.0.0.1:18833'
NAME='stmrep-browser-test'


def main():
    subprocess.run(['docker','run','-d','--name',NAME,'--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--tmpfs','/app/.data:uid=10929,gid=10929,mode=700',
        '--tmpfs','/tmp/stmrep:uid=10929,gid=10929,mode=700','-p','127.0.0.1:18833:8000',
        '-e','APP_MODE=demo','-e','WORKER_ENABLED=false','-e','COOKIE_SECURE=false','stmrep:release-test'],check=True,stdout=subprocess.PIPE)
    checks=[]
    try:
        for _ in range(60):
            try:
                if requests.get(BASE+'/healthz',timeout=3).status_code==200:break
            except requests.RequestException:pass
            time.sleep(1)
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for token_key in ('marketplace_token','marketplace-token'):
                context=browser.new_context();page=context.new_page();seen=[];errors=[]
                page.on('pageerror',lambda e:errors.append(str(e)))
                def session_route(route):
                    if route.request.method=='POST':
                        body=route.request.post_data_json
                        assert body=={'session_code':'SYNTHETIC_SESSION','marketplace_token':'SYNTHETIC_TOKEN'}
                        seen.append(body)
                        response=context.request.post(BASE+'/api/session/demo')
                        route.fulfill(response=response)
                    else:route.continue_()
                page.route('**/api/session',session_route)
                page.goto(BASE+f'/?bms-session-id=SYNTHETIC_SESSION&{token_key}=SYNTHETIC_TOKEN&view=cases#folder')
                page.get_by_role('heading',name='บัญชีภาพรวม',exact=True).wait_for()
                assert len(seen)==1 and page.url==BASE+'/?view=cases#folder'
                assert page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length')==0
                for width in (1440,390):
                    page.set_viewport_size({'width':width,'height':900})
                    assert not page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
                page.set_viewport_size({'width':1440,'height':900})
                page.get_by_role('button',name='REP รอ STM 20',exact=True).click()
                expect(page.locator('table.case-table tbody tr')).to_have_count(20)
                page.locator('table.case-table .cell-link').first.click()
                page.get_by_role('dialog').wait_for()
                assert page.get_by_role('dialog').get_attribute('aria-labelledby')
                page.get_by_role('button',name='ปิดแฟ้ม',exact=True).click()
                assert not errors
                context.close();checks.append('URL Session '+token_key+'/single handshake/clean URL/storage/cases/mobile')
            context=browser.new_context();page=context.new_page();page.clock.install()
            page.route('**/api/health',lambda route:route.fulfill(json={'status':'ok','mode':'live'}))
            def failed(route):route.fulfill(status=403,json={'error':'HOSPITAL_MISMATCH'})
            page.route('**/api/session',failed)
            page.goto(BASE+'/?bms-session-id=SYNTHETIC_WRONG_HOSPITAL&marketplace_token=SYNTHETIC_TOKEN')
            page.get_by_text('Session นี้ไม่ใช่โรงพยาบาล 10929',exact=False).wait_for()
            assert 'SYNTHETIC' not in page.url
            assert page.get_by_label('รหัส BMS Session',exact=True).input_value()==''
            page.unroute('**/api/session',failed)
            def reconnect(route):route.fulfill(response=context.request.post(BASE+'/api/session/demo'))
            page.route('**/api/session',reconnect)
            page.get_by_label('รหัส BMS Session',exact=True).fill('SYNTHETIC_RECONNECT')
            page.get_by_role('button',name='เชื่อมต่อ Session',exact=True).click()
            page.get_by_role('heading',name='บัญชีภาพรวม',exact=True).wait_for()
            page.route('**/api/session',lambda route:route.fulfill(status=401,json={'error':'BMS_SESSION_EXPIRED'}))
            page.clock.fast_forward(61000)
            page.get_by_label('รหัส BMS Session',exact=True).wait_for()
            assert page.evaluate('Object.keys(localStorage).length+Object.keys(sessionStorage).length')==0
            context.close();browser.close();checks.append('hospital mismatch/manual reconnect/session expiration')
        report={'status':'passed','fixture':'synthetic_only','checks':checks}
        (ROOT/'.ci').mkdir(exist_ok=True)
        (ROOT/'.ci/browser-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
    finally:
        subprocess.run(['docker','rm','-f',NAME],check=True,stdout=subprocess.PIPE)


if __name__=='__main__':main()
