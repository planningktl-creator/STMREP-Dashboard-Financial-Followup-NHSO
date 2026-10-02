import {useState,useEffect,useRef,lazy,Suspense,type ReactNode,type FormEvent} from 'react';
import {Activity,ArrowRight,BookOpen,Check,ChevronLeft,ChevronRight,ClipboardList,Clock,Database,FileCheck2,FileUp,FolderOpen,LayoutDashboard,LogOut,RefreshCw,Search,ShieldCheck,SlidersHorizontal,TriangleAlert,X} from 'lucide-react';
import {api,post,setCsrf,money,count,day,statusNames,message,ApiError,type Row} from './api';
import {captureLaunch} from './launch';
import {useApi,useVisiblePolling,currentFY,fyScope,scoped,Badge,Empty,Notice,Loading,Panel,type Scope} from './shared';

const CaseFile=lazy(()=>import('./CaseFile'));
const Imports=lazy(()=>import('./SecondaryScreens').then(m=>({default:m.Imports})));
const His=lazy(()=>import('./SecondaryScreens').then(m=>({default:m.His})));
const Appeals=lazy(()=>import('./SecondaryScreens').then(m=>({default:m.Appeals})));
const Quality=lazy(()=>import('./SecondaryScreens').then(m=>({default:m.Quality})));
const Dictionary=lazy(()=>import('./SecondaryScreens').then(m=>({default:m.Dictionary})));
const Planning=lazy(()=>import('./SecondaryScreens').then(m=>({default:m.Planning})));

let launch=captureLaunch(window.location,window.history);
let launchPromise:Promise<Row>|undefined;
function initialSession(){
 if(!launchPromise){
  const payload=launch;launch=null;
  launchPromise=payload?(payload.error?Promise.reject(new ApiError(payload.error,422)):post('/session',payload)):api('/session');
 }
 return launchPromise;
}

type Screen='dashboard'|'cases'|'followup'|'imports'|'his'|'appeals'|'quality'|'dictionary'|'planning';
const nav:[Screen,string,typeof Activity][]=[['dashboard','ภาพรวมการเบิกจ่าย',LayoutDashboard],['cases','แฟ้มรายเคส',FolderOpen],['followup','คิวติดตาม',ClipboardList],['appeals','อุทธรณ์',FileCheck2],['imports','นำเข้า REP / STM',FileUp],['his','ข้อมูล HIS',Database],['quality','คุณภาพข้อมูล',ShieldCheck],['dictionary','Data Dictionary',BookOpen],['planning','วางแผน',SlidersHorizontal]];

export default function App(){
 const [session,setSession]=useState<Row|null>(null),[health,setHealth]=useState<Row|null>(null),[ready,setReady]=useState(false),[screen,setScreen]=useState<Screen>('dashboard'),[launchError,setLaunchError]=useState('');
 const [serviceError,setServiceError]=useState(''),[checkingService,setCheckingService]=useState(false);
 const checkService=async()=>{setCheckingService(true);setServiceError('');try{setHealth(await api('/health'));}catch(e){setHealth(null);setServiceError(message(e));}finally{setCheckingService(false);}};
 const [scope,setScope]=useState<Scope>(fyScope(currentFY())),[snapshots,setSnapshots]=useState<Row[]>([]),[refresh,setRefresh]=useState(0),[caseId,setCaseId]=useState<number|null>(null),[stage,setStage]=useState(''),[toast,setToast]=useState('');
 useEffect(()=>{void checkService();initialSession().then(s=>{setCsrf(s.csrf);setSession(s);}).catch(e=>{if(e.code!=='BMS_SESSION_REQUIRED')setLaunchError(message(e));}).finally(()=>setReady(true));},[]);
 useEffect(()=>{if(!session)return;api('/snapshots').then(x=>{setSnapshots(x.items);if(session.mode==='demo'&&x.items[0])setScope({start:x.items[0].dstart,end:x.items[0].dend,snapshot:x.items[0].id});}).catch(e=>setToast(message(e)));},[session]);
 useVisiblePolling(Boolean(session),()=>{api('/session').catch(e=>{if(e.status===401){setSession(null);setCsrf('');}});},60000);
 const notify=(value:string)=>{setToast(value);setRefresh(x=>x+1);};
 const openStage=(status:string)=>{setStage(status);setScreen('cases');};
 if(!ready)return <div className="login-page"><section><Loading/>{serviceError&&<Notice tone="error">บริการยังไม่พร้อม · {serviceError}</Notice>}</section></div>;
 if(!session)return <Login demo={health?.mode==='demo'} initialError={launchError} serviceError={serviceError} checkingService={checkingService} checkService={checkService} onConnect={s=>{setCsrf(s.csrf);setSession(s);setToast('');setLaunchError('');}}/>;
 return <div className="app-shell">
  <a className="skip" href="#main">ข้ามไปเนื้อหา</a>
  <aside className="sidebar"><div className="brand"><div className="brand-mark"><Activity size={23}/></div><div>STMREP<span>FINANCIAL FOLLOW-UP</span></div></div><div className="hospital-label">โรงพยาบาล 10929 <span className="connection-dot"/></div>
   <nav aria-label="เมนูหลัก">{nav.map(([id,label,Icon])=><button key={id} className={screen===id?'active':''} onClick={()=>{setScreen(id);setStage('');}} aria-current={screen===id?'page':undefined}><Icon size={19}/><span>{label}</span>{id==='followup'&&<span className="nav-dot"/>}</button>)}</nav>
   <div className="sidebar-foot"><p>HIS → REP → STM</p><small>ทุกยอดมีที่มา<br/>ทุกเคสมีขั้นตอนถัดไป</small><button onClick={async()=>{try{await api('/session',{method:'DELETE'});}finally{setSession(null);setCsrf('');}}}><LogOut size={17}/> ออกจาก Session</button></div>
  </aside>
  <div className="workspace"><header className="topbar"><span className="breadcrumb">ทะเบียนการเบิกจ่าย <ChevronRight size={14}/><strong>{nav.find(x=>x[0]===screen)?.[1]}</strong></span><span className="session-label"><ShieldCheck size={16}/> {session.mode==='demo'?'ข้อมูลจำลอง':'BMS Session · 10929'}<span className="small">หมดอายุ {new Date(session.expires_at*1000).toLocaleTimeString('th-TH',{hour:'2-digit',minute:'2-digit'})}</span></span></header>
   {session.mode==='demo'&&<div className="demo-strip">โหมดสาธิต · ทุกเคสและยอดเงินเป็นข้อมูลจำลอง ไม่มีการเชื่อม HIS หรือฐานข้อมูลจริง</div>}
   <main id="main"><div className="page-heading"><div><h1>{nav.find(x=>x[0]===screen)?.[1]}</h1><p>{screen==='dashboard'?'เห็นต้นทางของเคส ติดตามผลการเบิก และเปิดหลักฐานได้ในแฟ้มเดียว':'ตรวจต้นทางและบันทึกขั้นตอนถัดไปของแต่ละเคส'}</p></div><button className="button secondary" onClick={()=>setRefresh(x=>x+1)}><RefreshCw size={16}/> โหลดข้อมูลใหม่</button></div>
    {toast&&<div className="toast" role="status">{toast}<button className="icon-button" aria-label="ปิดข้อความ" onClick={()=>setToast('')}><X size={17}/></button></div>}
    {['dashboard','cases','followup'].includes(screen)&&<ScopeBar scope={scope} setScope={s=>{setScope(s);setRefresh(x=>x+1);}} snapshots={snapshots}/>}
    {screen==='dashboard'&&<Dashboard scope={scope} refresh={refresh} openCase={setCaseId} openStage={openStage}/>}
    {(screen==='cases'||screen==='followup')&&<Cases scope={scope} refresh={refresh} openCase={setCaseId} stage={stage} followup={screen==='followup'}/>}
    <Suspense fallback={<Loading/>}>
    {screen==='imports'&&<Imports refresh={refresh} notify={notify} demo={session.mode==='demo'}/>}
    {screen==='his'&&<His refresh={refresh} notify={notify} snapshots={snapshots} onSnapshotRefresh={()=>api('/snapshots').then(x=>setSnapshots(x.items))} demo={session.mode==='demo'}/>}
    {screen==='appeals'&&<Appeals refresh={refresh} openCases={()=>setScreen('cases')}/>}
    {screen==='quality'&&<Quality refresh={refresh} snapshot={scope.snapshot}/>}
    {screen==='dictionary'&&<Dictionary/>}
    {screen==='planning'&&<Planning/>}
    </Suspense>
    <footer className="workspace-footer">STMREP · โรงพยาบาล 10929<span>ค่าเรียกเก็บ ≠ ต้นทุน · STM ต้องมีหลักฐานโอนก่อนเป็นเงินรับ</span></footer>
   </main>
  </div>
  <Suspense fallback={<Loading/>}>{caseId!==null&&<CaseFile id={caseId} onClose={()=>setCaseId(null)} notify={notify} demo={session.mode==='demo'}/>}</Suspense>
 </div>;
}

function Login({demo,onConnect,initialError='',serviceError,checkingService,checkService}:{demo:boolean,onConnect:(s:Row)=>void,initialError?:string,serviceError:string,checkingService:boolean,checkService:()=>void}){
 const [code,setCode]=useState(''),[marketplace,setMarketplace]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState(initialError);
 const connect=async(event?:FormEvent)=>{event?.preventDefault();setBusy(true);setError('');try{onConnect(await post(demo?'/session/demo':'/session',{session_code:code.trim(),marketplace_token:marketplace||undefined}));setCode('');setMarketplace('');}catch(e){setError(message(e));}finally{setBusy(false);}};
 return <div className="login-page"><div className="login-intro"><div className="login-brand"><Activity size={30}/> STMREP · 10929</div><h1>ติดตามการเบิกจ่าย<br/>จากเคสถึงหลักฐาน</h1><p>ใช้ HIS เป็นตัวตั้ง เชื่อมผล REP และ STM<br/>ให้เคสที่ต้องติดตามมีเจ้าของและขั้นตอนถัดไป</p><div className="login-rail"><span>01 HIS</span><ArrowRight size={18}/><span>02 REP</span><ArrowRight size={18}/><span>03 STM</span></div></div><section className="login-form"><span className="folder-tab">เชื่อมต่อข้อมูล</span><h2>{demo?'เปิดแฟ้มสาธิต':'เข้าใช้งานด้วย BMS Session'}</h2><p>{demo?'ทดลองหน้าจอด้วยข้อมูลจำลอง โดยไม่อ่านหรือส่งข้อมูลผู้ป่วยจริง':'Backend จะตรวจโรงพยาบาล ปลายทาง และอายุ Session ก่อนเข้าใช้งาน'}</p><div aria-live="polite">{serviceError&&<><Notice tone="error">บริการยังไม่พร้อม · {serviceError}</Notice><button className="button secondary" type="button" disabled={checkingService} onClick={checkService}><RefreshCw size={16}/>{checkingService?'กำลังตรวจบริการ…':'ตรวจบริการอีกครั้ง'}</button></>}</div><form onSubmit={connect}>{!demo&&<><label>รหัส BMS Session<input value={code} onChange={e=>setCode(e.target.value)} type="password" autoComplete="off" required maxLength={512}/></label><details><summary>Marketplace token (หาก API กำหนด)</summary><label>Token<input type="password" autoComplete="off" value={marketplace} onChange={e=>setMarketplace(e.target.value)}/></label></details></>}{error&&<Notice tone="error">{error}</Notice>}<button className="button primary wide" disabled={busy}>{busy?'กำลังตรวจ Session…':demo?'เข้าสู่ข้อมูลจำลอง':'เชื่อมต่อ Session'}<ArrowRight size={17}/></button></form><small><ShieldCheck size={15}/> Session เก็บฝั่ง server และไม่บันทึกลง browser storage</small></section></div>;
}

function ScopeBar({scope,setScope,snapshots}:{scope:Scope,setScope:(s:Scope)=>void,snapshots:Row[]}){
 const startFy=Number(scope.start.slice(0,4))+543+(Number(scope.start.slice(5,7))>=10?1:0),endFy=Number(scope.end.slice(0,4))+543+(Number(scope.end.slice(5,7))>=10?1:0),fy=startFy===endFy?String(startFy):'custom';
 return <div className="scope-bar"><label>ปีงบประมาณ<select value={fy} onChange={e=>{if(e.target.value!=='custom')setScope({...fyScope(Number(e.target.value)),snapshot:scope.snapshot});}}><option value="custom">ช่วงวันที่กำหนดเอง</option>{Array.from({length:12},(_,i)=>currentFY()-i).map(v=><option key={v} value={v}>{v}</option>)}</select></label><label>ตั้งแต่<input type="date" value={scope.start} max={scope.end} onChange={e=>setScope({...scope,start:e.target.value})}/></label><label>ถึง<input type="date" value={scope.end} min={scope.start} onChange={e=>setScope({...scope,end:e.target.value})}/></label><label className="snapshot-select">ชุดข้อมูล HIS<select value={scope.snapshot} onChange={e=>setScope({...scope,snapshot:e.target.value})}><option value="">ฉบับล่าสุดที่พร้อมใช้งาน</option>{snapshots.map(s=><option key={s.id} value={s.id}>{day(s.dstart)} – {day(s.dend)} · {s.status}</option>)}</select></label></div>;
}

function Dashboard({scope,refresh,openCase,openStage}:{scope:Scope,refresh:number,openCase:(n:number)=>void,openStage:(s:string)=>void}){
 const {data,error,loading}=useApi('/overview?'+scoped(scope),refresh);
 if(loading&&!data)return <Loading/>;if(error)return <Notice tone="error">{error}</Notice>;if(!data)return null;
 const f=data.financial||{},h=data.his||{},meta=data.meta||{};
 return <>
  {!meta.range_covered&&meta.mode!=='demo'&&<Notice>ช่วงวันที่เลือกยังไม่ครอบคลุมด้วย snapshot นี้ ยอดแสดงเฉพาะข้อมูลที่อ่านพบ ไม่ใช่ความครบถ้วนทั้งโรงพยาบาล</Notice>}
  {meta.refresh_state==='pending'&&<Notice>มีข้อมูลใหม่รอปรับคู่เชื่อมและรายงาน ยอดที่เห็นยังไม่ใช่ผลปรับครบ</Notice>}
  {meta.statement_cache?.stale&&<Notice>REP / STM มีรายการใหม่รอปรับรายงาน ยอด cache เดิมยังไม่พร้อมรับรอง · {count(meta.statement_cache.dirty?.claims)} เคลมรอปรับ</Notice>}
  <div className="source-line"><span><span className="connection-dot"/> {data.his?'ตัวตั้งจาก encounter ใน HIS':'ยังไม่มี snapshot HIS'}</span><span>ข้อมูล ณ {day(meta.as_of)} · OPD วันบริการ / IPD วันจำหน่าย</span></div>
  <section className="evidence-rail" aria-label="ขั้นตอนหลักฐานการเงิน"><button onClick={()=>openStage('SUBMISSION_UNVERIFIED')}><span className="rail-index">01 / ต้นทาง</span><div><Database size={22}/><h2>HIS</h2></div><strong>{count(h.encounters)}</strong><span>ครั้งรับบริการที่จัดช่วงเวลาได้</span><small>OPD {count(h.op_visits)} · IPD {count(h.ip_admissions)}</small></button><ArrowRight className="rail-arrow"/><button onClick={()=>openStage('STM_PENDING')}><span className="rail-index">02 / ผลการส่งเบิก</span><div><FileCheck2 size={22}/><h2>REP</h2></div><strong>{money(f.rep_nhso_amount)} <em>บาท</em></strong><span>ชดเชยส่วน สปสช. ที่จับคู่ได้</span><small>{count(data.sources?.find((s:Row)=>s.source==='REP')?.files)} ไฟล์ในฐานข้อมูล</small></button><ArrowRight className="rail-arrow"/><button onClick={()=>openStage('STATEMENT_PARTIAL')}><span className="rail-index">03 / Statement</span><div><ClipboardList size={22}/><h2>STM</h2></div><strong>{money(f.stm_net_amount)} <em>บาท</em></strong><span>ยอดสุทธิตาม statement ที่จับคู่ได้</span><small>ยังไม่ใช่หลักฐานเงินโอน</small></button></section>
  <div className="dashboard-grid"><div className="dashboard-main"><Panel title="บัญชีภาพรวม" caption={`ผู้มารับบริการ ${count(h.patients)} คน · ทะเบียนทั้งหมด ${count(h.registry?.registry_hn)} HN · ยังนอน ${count(h.unallocated_dates?.active_admissions)} AN`}><dl className="money-ledger">{[['ค่าเรียกเก็บ HIS',f.his_charge_amount,'รายการรักษา / สรุป HIS ตาม coverage'],['ยอดส่งเบิกที่มีหลักฐาน',f.submitted_amount,'ใช้รอบล่าสุดของแต่ละองค์ประกอบ'],['ต้นทุนรายการที่ยืนยัน',f.observed_item_cost,`มีต้นทุน ${count(f.cost_known_count)} / ${count(f.line_count)} รายการ`],['ต้นทุนประมาณการ',f.estimated_item_cost,'ราคาปัจจุบันจากทะเบียนรายการ'],['เงินรับที่จัดสรรถึงเคส',f.cash_received_amount,'ต้องมีหลักฐานโอนและผ่านการตรวจ']].map(([label,value,hint])=><div key={label}><dt>{label}<small>{hint}</small></dt><dd>{money(value)}<span>บาท</span></dd></div>)}</dl></Panel>
   <Panel title="แนวโน้มตามเดือนบริการ" caption="เปรียบเทียบยอดบนขอบเขตข้อมูลเดียวกัน"><Trend rows={data.trend||[]}/></Panel>
  </div><aside className="work-queue"><Panel title="ขั้นตอนที่ต้องติดตาม" caption="เลือกกลุ่มเพื่อเปิดทะเบียนเคส"><div className="status-stack">{data.status_counts?.length?data.status_counts.map((s:Row)=><button key={s.tracking_status} onClick={()=>openStage(s.tracking_status)}><span className={'status-dot '+(s.tracking_status==='MATCHED'?'green':'amber')}/><span>{statusNames[s.tracking_status]||s.tracking_status}</span><strong>{count(s.count)}</strong><ChevronRight size={15}/></button>):<Empty title="รอตัวตั้ง HIS">อ่าน HIS เพื่อแสดงคิวเคสที่ต้องติดตาม</Empty>}</div><div className="queue-divider">แฟ้มที่ควรเปิดตรวจ</div>{data.worklist?.slice(0,5).map((c:Row)=><button className="queue-case" key={c.id} onClick={()=>openCase(c.id)}><span className="case-stamp">{c.care_type}</span><div><strong>HN {c.hn||'—'}</strong><small>{statusNames[c.tracking_status]} · {c.aging?.days??'—'} วันจากบริการ</small></div><ChevronRight size={16}/></button>)}</Panel><div className="scope-note"><BookOpen size={18}/><strong>ตัวหารต้องผ่านกฎสิทธิก่อน</strong><p>การพบ REP หรือ STM ยังไม่ยืนยันว่าเรียกเก็บครบทุกบริการ อัตราความครบถ้วนจะแสดงเมื่อกฎและตัวตั้งผ่านตรวจ</p></div></aside></div>
  {!data.his&&<Empty title="เริ่มด้วยข้อมูล HIS">ไปที่ “ข้อมูล HIS” เพื่ออ่าน encounter ในช่วงเวลาที่ต้องการ REP และ STM เดิมยังอยู่ในฐานข้อมูล</Empty>}
  <div className="metadata-line">Snapshot: {meta.snapshot_id||'ยังไม่มี'} · contributing: ค่าเรียกเก็บ {count(f.charge_contributing_count)} เคส / STM {count(f.stm_contributing_count)} เคส</div>
 </>;
}

function Trend({rows}:{rows:Row[]}){
 if(!rows.length)return <Empty title="ยังไม่มีข้อมูลในช่วงที่เลือก">เลือกช่วงที่ครอบคลุมด้วย snapshot</Empty>;
 const max=Math.max(...rows.map(r=>Number(r.his_charge_amount)||0),1);
 return <div className="trend"><div className="chart-legend"><span><i className="his"/>ค่าเรียกเก็บ HIS</span><span><i className="rep"/>REP ส่วน สปสช.</span><span><i className="stm"/>STM</span></div><div className="chart-bars">{rows.map(r=><div className="chart-month" key={r.month}><div className="bar-group">{[['his','his_charge_amount'],['rep','rep_nhso_amount'],['stm','stm_net_amount']].map(([cls,f])=><div className={'bar '+cls} style={{height:r[f]===null?'0':`${Math.max(2,Number(r[f])/max*100)}%`}} key={f} title={`${r.month} ${f}: ${money(r[f])} บาท`}/>)}</div><span>{r.month}</span></div>)}</div><details className="chart-data"><summary>ดูค่าตัวเลข</summary><div className="table-scroll"><table><thead><tr><th>เดือน</th><th className="num">HIS</th><th className="num">REP</th><th className="num">STM</th></tr></thead><tbody>{rows.map(r=><tr key={r.month}><td>{r.month}</td><td className="num">{money(r.his_charge_amount)}</td><td className="num">{money(r.rep_nhso_amount)}</td><td className="num">{money(r.stm_net_amount)}</td></tr>)}</tbody></table></div></details></div>;
}

function Cases({scope,refresh,openCase,stage,followup}:{scope:Scope,refresh:number,openCase:(n:number)=>void,stage:string,followup:boolean}){
 const [care,setCare]=useState(''),[status,setStatus]=useState(stage||(followup?'FOLLOWUP':'')),[search,setSearch]=useState(''),[query,setQuery]=useState(''),[cursor,setCursor]=useState(0),[history,setHistory]=useState<number[]>([]),[orphans,setOrphans]=useState(false);
 useEffect(()=>{setStatus(stage||(followup?'FOLLOWUP':''));setCursor(0);setHistory([]);},[stage,scope]);
 useEffect(()=>{const timer=setTimeout(()=>{setQuery(search.trim());setCursor(0);setHistory([]);},300);return()=>clearTimeout(timer);},[search]);
 const params={...(care?{care}:{}),...(status?{status}:{}),...(query?{search:query}:{}),cursor:String(cursor),limit:'50'};
 const {data,error,loading}=useApi((orphans?'/orphans?':'/cases?')+scoped(scope,params),refresh);
 const reset=()=>{setCursor(0);setHistory([]);};
 return <Panel title={orphans?'REP / STM ที่ยังไม่พบ HIS':followup?'ทะเบียนเคสสำหรับติดตาม':'ทะเบียนแฟ้มรายเคส'} caption="หนึ่งแถวต่อ encounter · โหลดครั้งละ 50 เคส"><form className="table-filters" onSubmit={e=>{e.preventDefault();setQuery(search);reset();}}><label className="search-field"><Search size={17}/><input aria-label="ค้นชื่อ HN AN VN" placeholder="ค้น HN, AN, VN หรือชื่อ" value={search} onChange={e=>setSearch(e.target.value)}/></label><button className="button secondary">ค้นหา</button><select aria-label="ประเภทบริการ" value={care} onChange={e=>{setCare(e.target.value);reset();}}><option value="">OPD และ IPD</option><option value="OP">OPD</option><option value="IP">IPD</option></select><select aria-label="สถานะเคส" value={status} onChange={e=>{setStatus(e.target.value);reset();}}><option value="">ทุกสถานะ</option><option value="FOLLOWUP">เคสต้องติดตาม / มีงานเปิด</option>{Object.entries(statusNames).filter(([k])=>k===k.toUpperCase()).map(([k,v])=><option value={k} key={k}>{v}</option>)}</select></form>
  <div className="folder-tabs"><button className={!orphans?'selected':''} onClick={()=>{setOrphans(false);reset();}}>ตัวตั้ง HIS</button><button className={orphans?'selected':''} onClick={()=>{setOrphans(true);reset();}}>REP / STM ไม่มีคู่ HIS</button></div>
  {followup&&<div className="inline-caption">อายุรายการอิงวันบริการ ใช้จัดลำดับงานทั่วไป · กำหนดส่งตามกฎยังต้องยืนยัน</div>}
  {error&&<Notice tone="error">{error}</Notice>}{loading&&<Loading/>}
  {!loading&&data?.items?.length===0&&<Empty title="ไม่พบเคสในขอบเขตนี้">ลองเปลี่ยนช่วงเวลา ตัวกรอง หรืออ่าน HIS ให้ครอบคลุม</Empty>}
  {!!data?.items?.length&&<div className="table-scroll"><table className="case-table"><thead><tr><th>แฟ้ม / ผู้รับบริการ</th><th>บริการ / สิทธิ</th>{!orphans&&<><th className="num">ค่าเรียกเก็บ HIS</th><th className="num">REP · สปสช.</th><th className="num">STM สุทธิ</th><th>ขั้นตอน / อายุ</th><th aria-label="เปิดแฟ้ม"/></>}</tr></thead><tbody>{data.items.map((c:Row)=><tr key={c.id}><td>{orphans?<><strong>{c.tran_id}</strong><small>HN {c.hn||'—'} · AN {c.an||'—'}</small></>:<button className="cell-link" onClick={()=>openCase(c.id)}><strong>HN {c.hn||'ยังไม่ทราบ'}</strong><span>{c.name||'ไม่พบทะเบียนผู้ป่วย'} · {c.an||c.vn||'—'}</span></button>}</td><td><span className="care-label">{c.care_type||c.patient_type}</span><small>{day(c.service_date)} · {c.pttype||c.payer_family||'สิทธิยังไม่ทราบ'}</small></td>{!orphans&&<><td className="num">{money(c.his_charge_amount)}</td><td className="num">{money(c.rep_nhso_amount)}</td><td className="num">{money(c.stm_net_amount)}</td><td><Badge value={c.tracking_status}/><small><Clock size={12}/> {c.aging?.days??'—'} วันจากบริการ</small><small>{c.task_teams||'ยังไม่มอบหมาย'} · {day(c.next_followup_date)}</small></td><td><button className="icon-button" aria-label={`เปิดแฟ้ม ${c.hn}`} onClick={()=>openCase(c.id)}><ChevronRight size={18}/></button></td></>}</tr>)}</tbody></table></div>}
  <div className="pagination"><span>{count(data?.count)} เคสในตัวกรอง · ไม่รวมแถววินิจฉัยหรือยาเป็นเคสเพิ่ม</span><div><button className="button secondary" disabled={!history.length||loading} onClick={()=>{setCursor(history[history.length-1]);setHistory(history.slice(0,-1));}}><ChevronLeft size={15}/> ก่อนหน้า</button><button className="button secondary" disabled={!data?.next_cursor||loading} onClick={()=>{setHistory([...history,cursor]);setCursor(data!.next_cursor);}}>ถัดไป <ChevronRight size={15}/></button></div></div>
 </Panel>;
}
