import ts from 'typescript';
import vm from 'node:vm';
import fs from 'node:fs';
import assert from 'node:assert/strict';
const source=fs.readFileSync(new URL('../src/launch.ts',import.meta.url),'utf8');
const compiled=ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText;
const sandbox={exports:{},URL};vm.runInNewContext(compiled,sandbox);
let checks=0;
function run(query){
 let clean=null;
 const result=sandbox.exports.captureLaunch({href:'https://dashboard.example.invalid/'+query},{state:null,replaceState:(_state,_title,path)=>{clean=path;}});
 if(clean!==null)for(const key of ['bms-session-id','marketplace_token','marketplace-token'])assert(!new URL(clean,'https://example.invalid').searchParams.has(key));
 checks++;return {result,clean};
}
for(const key of ['marketplace_token','marketplace-token']){
 const {result,clean}=run(`?bms-session-id=SYNTHETIC&${key}=SYNTHETIC_TOKEN&view=cases#details`);
 assert.equal(result.session_code,'SYNTHETIC');assert.equal(result.marketplace_token,'SYNTHETIC_TOKEN');assert.equal(clean,'/?view=cases#details');
}
assert.equal(run('?view=cases').result,null);
assert.equal(run('?marketplace-token=SYNTHETIC').result.error,'LAUNCH_PARAMS_INVALID');
assert.equal(run('?bms-session-id=A&bms-session-id=B').result.error,'LAUNCH_PARAMS_INVALID');
assert.equal(run('?bms-session-id=A&marketplace_token=A&marketplace-token=B').result.error,'LAUNCH_PARAMS_INVALID');
assert.equal(run('?bms-session-id=%00').result.error,'LAUNCH_PARAMS_INVALID');
assert.equal(run('?bms-session-id=SYNTHETIC').result.session_code,'SYNTHETIC');
console.log(JSON.stringify({status:'passed',checks,fixture:'synthetic_only'}));
