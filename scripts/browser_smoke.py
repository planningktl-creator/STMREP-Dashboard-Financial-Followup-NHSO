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


def optimization_checks(browser):
    context=browser.new_context();page=context.new_page();page.clock.install()
    page.goto(BASE)
    page.get_by_role('button',name='เข้าสู่ข้อมูลจำลอง',exact=True).click()
    try:page.get_by_role('heading',name='บัญชีภาพรวม',exact=True).wait_for()
    except Exception:
        print(json.dumps({'synthetic_browser_alerts':page.get_by_role('alert').all_text_contents(),'synthetic_headings':page.get_by_role('heading').all_text_contents()},ensure_ascii=False))
        raise
    (ROOT/'.ci').mkdir(exist_ok=True)
    for width,label in [(1440,'desktop'),(390,'mobile')]:
        page.set_viewport_size({'width':width,'height':900})
        assert not page.evaluate('document.documentElement.scrollWidth>window.innerWidth')
        page.screenshot(path=str(ROOT/'.ci'/f'optimized-{label}.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':900})
    requests_seen=[]
    def cases(route):
        from urllib.parse import urlparse,parse_qs
        query=parse_qs(urlparse(route.request.url).query).get('search',[''])[0]
        requests_seen.append(query)
        route.fulfill(json={'items':[],'count':0,'next_cursor':None,'meta':{}})
    page.route('**/api/cases?*',cases)
    page.get_by_role('button',name='แฟ้มรายเคส',exact=True).click()
    page.get_by_label('ค้นชื่อ HN AN VN',exact=True).wait_for()
    requests_seen.clear()
    page.get_by_label('ค้นชื่อ HN AN VN',exact=True).fill('000')
    page.clock.fast_forward(200)
    page.get_by_label('ค้นชื่อ HN AN VN',exact=True).fill('000001')
    page.clock.fast_forward(301)
    expect(page.locator('.loading')).to_have_count(0)
    page.wait_for_timeout(100)
    assert requests_seen==['000001'],requests_seen
    pending=[];aborted=[]
    page.on('requestfailed',lambda request:aborted.append(request.url))
    def delayed_cases(route):
        from urllib.parse import urlparse,parse_qs
        query=parse_qs(urlparse(route.request.url).query).get('search',[''])[0]
        if query=='old':pending.append(route);return
        route.fulfill(json={'items':[{'id':1,'hn':'SYNTHETIC-NEW','care_type':'IP','tracking_status':'MATCHED'}],'count':1,'next_cursor':None,'meta':{}})
    page.route('**/api/cases?*',delayed_cases)
    with page.expect_request(lambda request:'search=old' in request.url):
        page.get_by_label('ค้นชื่อ HN AN VN',exact=True).fill('old');page.clock.fast_forward(301)
    with page.expect_response(lambda response:'search=new' in response.url):
        page.get_by_label('ค้นชื่อ HN AN VN',exact=True).fill('new');page.clock.fast_forward(301)
    page.get_by_role('button',name='HN SYNTHETIC-NEW',exact=False).first.wait_for()
    # A canceled browser request may reject route.fulfill; either behavior must
    # keep its stale result off the screen.
    from playwright.sync_api import Error
    try:pending[0].fulfill(json={'items':[{'id':2,'hn':'SYNTHETIC-OLD'}],'count':1})
    except Error:pass
    page.wait_for_timeout(100)
    assert any('search=old' in url for url in aborted)
    expect(page.get_by_text('HN SYNTHETIC-OLD',exact=True)).to_have_count(0)
    jobs=[];status=['queued']
    def job_route(route):
        jobs.append(route.request.url)
        route.fulfill(json={'items':[{'id':'33333333-3333-4333-8333-333333333333','kind':'IMPORT','status':status[0],'progress':{}}]})
    page.route('**/api/jobs',job_route)
    with page.expect_response(lambda response:response.url.endswith('/api/jobs')):
        page.get_by_role('button',name='นำเข้า REP / STM',exact=True).click()
    page.get_by_role('heading',name='นำเข้า REP / STM',exact=True).wait_for()
    page.wait_for_timeout(100)
    assert len(jobs)==1
    page.clock.fast_forward(10001);page.wait_for_timeout(100)
    assert len(jobs)==2
    page.evaluate("Object.defineProperty(document,'visibilityState',{configurable:true,get:()=>window.__testVisibility||'visible'});window.__testVisibility='hidden';document.dispatchEvent(new Event('visibilitychange'))")
    page.clock.fast_forward(35000);page.wait_for_timeout(100)
    assert len(jobs)==2
    status[0]='completed'
    page.evaluate("window.__testVisibility='visible';document.dispatchEvent(new Event('visibilitychange'))")
    page.wait_for_timeout(100);assert len(jobs)==3
    page.clock.fast_forward(15000);page.wait_for_timeout(100);assert len(jobs)==3
    page.route('**/api/overview?*',lambda route:route.fulfill(status=200,content_type='text/event-stream',body='event: ping\ndata: {}\n\n'))
    page.get_by_role('button',name='ภาพรวมการเบิกจ่าย',exact=True).click()
    page.get_by_role('alert').filter(has_text='บริการส่งข้อมูลกลับไม่ถูกต้อง').wait_for()
    context.close()


def main():
    subprocess.run(['docker','run','-d','--name',NAME,'--read-only','--cap-drop','ALL',
        '--security-opt','no-new-privileges:true','--tmpfs','/app/.data:uid=10929,gid=10929,mode=700',
        '--tmpfs','/tmp/stmrep:uid=10929,gid=10929,mode=700','-p','127.0.0.1:18833:8000',
        '-e','APP_MODE=demo','-e','WORKER_ENABLED=false','-e','COOKIE_SECURE=false',
        '-e','APP_ORIGINS='+BASE,'stmrep:release-test'],check=True,stdout=subprocess.PIPE)
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
            context.close();checks.append('hospital mismatch/manual reconnect/session expiration')
            optimization_checks(browser)
            checks+=['300ms search debounce','stale request canceled and cannot overwrite new result','hidden-tab polling pauses/resumes','completed job stops polling','malformed HTTP 200 recovery','desktop/mobile screenshots']
            browser.close()
        report={'status':'passed','fixture':'synthetic_only','checks':checks}
        (ROOT/'.ci').mkdir(exist_ok=True)
        (ROOT/'.ci/browser-result.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report))
    finally:
        subprocess.run(['docker','rm','-f',NAME],check=True,stdout=subprocess.PIPE)


if __name__=='__main__':main()
