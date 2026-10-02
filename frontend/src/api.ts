export type Row = Record<string, any>;
let csrf = '';
export function setCsrf(value:string){csrf=value;}
export class ApiError extends Error { constructor(public code:string,public status:number){super(code);} }
export async function api(path:string, options:RequestInit&{timeoutMs?:number}={}):Promise<any>{
  const {timeoutMs,signal:callerSignal,...request}=options;
  const controller=new AbortController();
  const cancel=()=>controller.abort(callerSignal?.reason);
  if(callerSignal?.aborted)cancel();else callerSignal?.addEventListener('abort',cancel,{once:true});
  let timedOut=false;
  const budget=timeoutMs??(path.startsWith('/health')||path==='/session'&&!request.method?8000:request.body instanceof FormData?300000:95000);
  const timer=setTimeout(()=>{timedOut=true;controller.abort();},budget);
  try{
    controller.signal.throwIfAborted();
    const headers=new Headers(request.headers);
    if(request.body && !(request.body instanceof FormData))headers.set('Content-Type','application/json');
    if(request.method && request.method!=='GET')headers.set('X-CSRF-Token',csrf);
    const response=await fetch('/api'+path,{...request,signal:controller.signal,headers,credentials:'same-origin'});
    const contentType=response.headers.get('Content-Type')||'';
    let data:Row;
    try{
      if(!/^application\/(?:[\w.+-]+\+)?json\b/i.test(contentType))throw new Error();
      data=await response.json();
      if(!data||typeof data!=='object'||Array.isArray(data))throw new Error();
    }catch(e){
      if(controller.signal.aborted)throw e;
      throw new ApiError('INVALID_API_RESPONSE',response.status);
    }
    if(!response.ok){
      const code=response.status===404&&data.detail==='Not Found'?'API_ROUTE_NOT_FOUND':String(data.error||data.detail||'SERVICE_UNAVAILABLE');
      throw new ApiError(code,response.status);
    }
    if(path==='/health'&&(data.status!=='ok'||data.hospital!=='10929'||!data.version))throw new ApiError('INVALID_API_RESPONSE',response.status);
    return data;
  }catch(e){
    if(callerSignal?.aborted)throw callerSignal.reason;
    if(timedOut)throw new ApiError('API_TIMEOUT',0);
    if(e instanceof TypeError)throw new ApiError('NETWORK_UNAVAILABLE',0);
    throw e;
  }finally{
    clearTimeout(timer);callerSignal?.removeEventListener('abort',cancel);
  }
}
export const post=(path:string,body:Row={})=>api(path,{method:'POST',body:JSON.stringify(body)});
export const money=(value:any)=>value===null||value===undefined||value===''?'—':new Intl.NumberFormat('th-TH',{minimumFractionDigits:2,maximumFractionDigits:2}).format(value);
export const count=(value:any)=>value===null||value===undefined?'—':new Intl.NumberFormat('th-TH').format(Number(value));
export const day=(value:any)=>!value?'—':new Date(value).toLocaleDateString('th-TH',{day:'numeric',month:'short',year:'numeric'});
export const statusNames:Record<string,string>={MATCHED:'ยอดตรงกัน',STM_PENDING:'REP รอ STM',REP_PENDING:'รอผล REP',REP_REJECTED:'REP ปฏิเสธ',SUBMISSION_UNVERIFIED:'ยังไม่พบหลักฐานส่ง',STATEMENT_PARTIAL:'STM น้อยกว่ายอด REP',OVER_EXPECTED:'STM เกินยอด REP',MATCH_REVIEW:'คู่เคลมต้องตรวจ',AMOUNT_UNKNOWN:'ยังไม่ทราบยอด',ZERO_OR_REVERSAL:'ยอดศูนย์ / ปรับปรุง',SOURCE_INCOMPLETE:'ข้อมูลต้นทางไม่ครบ',REP_REVISION_REVIEW:'REP หลายรอบวันที่เท่ากัน',NOT_COVERED:'อยู่นอกขอบเขต STM',queued:'รอคิว',inspecting:'กำลังตรวจไฟล์',awaiting_import:'พร้อมให้นำเข้า',importing:'กำลังนำเข้า',syncing:'กำลังอ่าน HIS',refreshing:'ปรับผลรายงาน',verifying:'ตรวจความครบถ้วน',complete:'เสร็จแล้ว',complete_with_issues:'เสร็จพร้อมรายการตรวจ',waiting_session:'รอ Session ใหม่',paused:'พักงาน',failed:'ต้องทำต่อจาก checkpoint',blocked:'พักตรวจ mapping',open:'เปิดงาน',in_progress:'กำลังติดตาม',waiting:'รอข้อมูล',resolved:'ปิดงาน'};
export const errorNames:Record<string,string>={BMS_SESSION_REQUIRED:'Session หมดอายุ กรุณาเชื่อมต่อใหม่',HOSPITAL_MISMATCH:'Session นี้ไม่ใช่โรงพยาบาล 10929',BMS_TARGET_NOT_ALLOWLISTED:'ปลายทาง BMS ยังไม่อยู่ในรายการที่อนุญาต ให้ผู้ดูแลตั้งค่า host',BMS_POSTGRESQL_REQUIRED:'รุ่นนี้รองรับ HIS PostgreSQL',BMS_UNAVAILABLE:'ยังเชื่อม BMS ไม่ได้ กรุณาลองใหม่',SERVICE_UNAVAILABLE:'บริการยังไม่ตอบกลับ กรุณาลองใหม่ งานเดิมยังมี checkpoint',DEMO_DOES_NOT_READ_HIS:'โหมดจำลองไม่ได้อ่าน HIS',DEMO_DOES_NOT_ACCEPT_PATIENT_FILES:'โหมดจำลองไม่รับไฟล์ผู้ป่วย',BIFF_XLS_REQUIRED:'ต้องเป็นไฟล์ Excel .xls แบบ BIFF',SOURCE_FILENAME_INVALID:'ชื่อไฟล์ต้องขึ้นต้น STM_10929_ หรือ eclaim_10929_',NO_INSPECTED_FILES:'ไม่มีไฟล์ที่ผ่านการตรวจ',CSRF_TOKEN_REQUIRED:'กรุณาเชื่อม Session ใหม่'};
statusNames.completed='เสร็จแล้ว'; statusNames.completed_with_issues='เสร็จพร้อมรายการตรวจ';
statusNames.PAYMENT_SCOPE_REVIEW='หลายสิทธิ ต้องตรวจฐานเทียบ STM';
export function message(e:any){return errorNames[e.code]||'ดำเนินการไม่สำเร็จ · '+(e.code||e.message||'กรุณาลองใหม่');}
errorNames.LAUNCH_PARAMS_INVALID='พารามิเตอร์เปิดระบบไม่ถูกต้อง กรุณาเชื่อม Session ใหม่';
errorNames.REPORT_TIMEOUT='อ่านรายงานเกินเวลาที่กำหนด กรุณาลดช่วงวันที่หรือลองใหม่';
errorNames.INVALID_API_RESPONSE='บริการส่งข้อมูลกลับไม่ถูกต้อง กรุณาลองใหม่ หากยังพบปัญหาให้แจ้งผู้ดูแลตรวจ API และ gateway';
errorNames.SERVICE_DRAINING='ระบบกำลังอัปเดต กรุณาลองใหม่หลังบริการกลับมา';
errorNames.API_TIMEOUT='บริการตอบกลับไม่ทันเวลา กรุณาลองใหม่ หากเป็นงานนำเข้าให้ตรวจสถานะงานเดิมก่อนส่งซ้ำ';
errorNames.NETWORK_UNAVAILABLE='เชื่อมต่อบริการไม่ได้ กรุณาตรวจเครือข่ายและลองใหม่';
errorNames.API_ROUTE_NOT_FOUND='ยังเข้าถึง API ของ STMREP ไม่ได้ ให้ผู้ดูแลตรวจ container และ routing ของ /api';
errorNames.ORIGIN_REJECTED='โดเมน STMREP ยังไม่ได้รับอนุญาต กรุณาแจ้งผู้ดูแลตั้ง APP_ORIGINS ให้ตรงกับ URL ของระบบ';
