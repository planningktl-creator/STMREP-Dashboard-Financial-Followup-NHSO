import {useState,useEffect,useRef,type ReactNode} from 'react';
import {FolderOpen,TriangleAlert,RefreshCw} from 'lucide-react';
import {api,message,statusNames,type Row} from './api';
export type Scope={start:string,end:string,snapshot:string};
export function currentFY(){const d=new Date();return d.getFullYear()+543+(d.getMonth()>=9?1:0);}
export function fyScope(fy:number):Scope{return {start:`${fy-544}-10-01`,end:`${fy-543}-09-30`,snapshot:''};}
export function useApi(path:string|null,refresh=0){
 const [result,setResult]=useState<{path:string|null,data:Row|null}>({path:null,data:null}),[error,setError]=useState(''),[loading,setLoading]=useState(false);
 useEffect(()=>{if(!path)return;const controller=new AbortController();setLoading(true);setError('');
  api(path,{signal:controller.signal}).then(data=>{if(!controller.signal.aborted)setResult({path,data});}).catch(e=>{if(!controller.signal.aborted){setError(message(e));setResult({path,data:null});}}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();},[path,refresh]);
 return {data:result.path===path?result.data:null,error,loading};
}
export function useVisiblePolling(active:boolean,callback:()=>void,interval=10000){
 const latest=useRef(callback);latest.current=callback;
 useEffect(()=>{if(!active)return;let timer:ReturnType<typeof setInterval>|undefined;
  const stop=()=>{if(timer!==undefined)clearInterval(timer);timer=undefined;};
  const start=(resume=false)=>{stop();if(document.visibilityState==='hidden')return;if(resume)latest.current();timer=setInterval(()=>latest.current(),interval);};
  const changed=()=>start(true);start();document.addEventListener('visibilitychange',changed);
  return()=>{stop();document.removeEventListener('visibilitychange',changed);};},[active,interval]);
}

export const scoped=(scope:Scope,other:Row={})=>new URLSearchParams({start:scope.start,end:scope.end,...(scope.snapshot?{snapshot_id:scope.snapshot}:{}),...other}).toString();
export function Badge({value}:{value:string}){return <span className={`badge ${value==='MATCHED'||value==='complete'||value==='resolved'?'good':value==='REP_REJECTED'||value==='failed'?'bad':'review'}`}>{statusNames[value]||value}</span>;}
export function Empty({title,children}:{title:string,children?:ReactNode}){return <div className="empty"><FolderOpen size={28}/><h3>{title}</h3><p>{children}</p></div>;}
export function Notice({children,tone='warning'}:{children:ReactNode,tone?:string}){return <div className={`notice ${tone}`} role={tone==='error'?'alert':undefined}><TriangleAlert size={17}/><div>{children}</div></div>;}
export function Loading(){return <div className="loading" role="status"><RefreshCw size={18} className="spin"/> กำลังอ่านข้อมูล…</div>;}
export function Panel({title,caption,children,action}:{title:string,caption?:string,children:ReactNode,action?:ReactNode}){return <section className="sheet"><header className="sheet-header"><div><h2>{title}</h2>{caption&&<p>{caption}</p>}</div>{action}</header>{children}</section>;}
