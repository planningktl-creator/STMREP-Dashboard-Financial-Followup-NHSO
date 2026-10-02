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
console.log('API JSON, stream/proxy rejection, decimal/null and abort checks passed');
