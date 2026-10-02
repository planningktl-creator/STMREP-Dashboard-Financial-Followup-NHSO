// Only HEAD, main ref and packed refs enter the build stage. No git config,
// credentials, objects or clinical files enter the runtime image.
import {readFileSync,writeFileSync} from 'node:fs';
const read=path=>{try{return readFileSync(path,'utf8').trim();}catch{return '';}};
const hash=value=>/^[a-f0-9]{40}(?:[a-f0-9]{24})?$/.test(value);
let revision=process.env.BUILD_REVISION||'';
if(!hash(revision)){
 const head=read('/build/revision-input/HEAD');
 revision=hash(head)?head:head==='ref: refs/heads/main'?read('/build/revision-input/refs/heads/main'):'';
 if(!hash(revision)&&head==='ref: refs/heads/main')revision=read('/build/revision-input/packed-refs').split('\n').find(line=>line.endsWith(' refs/heads/main'))?.split(' ')[0]||'';
}
if(!hash(revision))revision='unknown';
writeFileSync('/build/build-revision',revision+'\n');
console.log('STMREP source revision: '+revision);
