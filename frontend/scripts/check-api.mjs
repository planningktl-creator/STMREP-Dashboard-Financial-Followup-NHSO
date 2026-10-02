import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from '../node_modules/typescript/lib/typescript.js';
const source=ts.transpileModule(readFileSync(new URL('../src/api.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const {api,ApiError}=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
for(const [body,type] of [['data: {"event":"keepalive"}\n\n','text/event-stream'],['<html>proxy</html>','text/html'],['{bad','application/json'],['null','application/json'],['[]','application/json']]){
 globalThis.fetch=async()=>new Response(body,{status:200,headers:{'Content-Type':type}});
 await assert.rejects(()=>api('/test'),e=>e instanceof ApiError&&e.code==='INVALID_API_RESPONSE'&&e.status===200);
}
globalThis.fetch=async()=>new Response('{"amount":"-0.001","missing":null}',{headers:{'Content-Type':'application/json'}});
assert.deepEqual(await api('/test'),{amount:'-0.001',missing:null});
globalThis.fetch=async()=>new Response('{"error":"BMS_SESSION_REQUIRED"}',{status:401,headers:{'Content-Type':'application/json'}});
await assert.rejects(()=>api('/test'),e=>e.code==='BMS_SESSION_REQUIRED');
const controller=new AbortController();controller.abort();
globalThis.fetch=async(_url,{signal})=>{signal.throwIfAborted();};
await assert.rejects(()=>api('/test',{signal:controller.signal}),e=>e.name==='AbortError');
// A gateway can leave fetch (or its body) pending indefinitely. It must not
// leave login/report controls busy forever, and a caller abort stays distinct.
globalThis.fetch=async(_url,{signal})=>new Promise((_resolve,reject)=>{
 signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
});
await assert.rejects(()=>api('/session',{timeoutMs:10}),e=>e instanceof ApiError&&e.code==='API_TIMEOUT');
globalThis.fetch=async(_url,{signal})=>({ok:true,status:200,headers:new Headers({'Content-Type':'application/json'}),
 json:()=>{signal.throwIfAborted();return new Promise((_resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));}});
await assert.rejects(()=>api('/test',{timeoutMs:10}),e=>e.code==='API_TIMEOUT');
const during=new AbortController();
const canceled=api('/test',{signal:during.signal});during.abort();
await assert.rejects(()=>canceled,e=>e.name==='AbortError');
globalThis.fetch=async()=>new Response('{"detail":"Not Found"}',{status:404,headers:{'Content-Type':'application/json'}});
await assert.rejects(()=>api('/session'),e=>e.code==='API_ROUTE_NOT_FOUND');
globalThis.fetch=async()=>new Response('{"status":"ok"}',{headers:{'Content-Type':'application/json'}});
await assert.rejects(()=>api('/health'),e=>e.code==='INVALID_API_RESPONSE');
globalThis.fetch=async()=>{throw new TypeError('Failed to fetch');};
await assert.rejects(()=>api('/test'),e=>e instanceof ApiError&&e.code==='NETWORK_UNAVAILABLE');
console.log('API JSON, proxy/404 rejection, decimal/null, body deadline, network and caller abort checks passed');
