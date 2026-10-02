export type Launch = {session_code:string;marketplace_token?:string;error?:string};

export function captureLaunch(location:Location, history:History):Launch|null {
 const url=new URL(location.href);
 const keys=['bms-session-id','marketplace_token','marketplace-token'];
 const present=keys.some(key=>url.searchParams.has(key));
 if(!present)return null;
 const codes=url.searchParams.getAll(keys[0]);
 const tokens=[...url.searchParams.getAll(keys[1]),...url.searchParams.getAll(keys[2])];
 for(const key of keys)url.searchParams.delete(key);
 history.replaceState(history.state,'',url.pathname+url.search+url.hash);
 const code=codes[0]?.trim()||'';
 const token=tokens[0];
 const invalid=codes.length!==1||!code||code.length>512||/[\x00-\x1f]/.test(code)||tokens.some(value=>value!==token)||tokens.some(value=>value.length>2048||/[\x00-\x1f]/.test(value));
 return invalid?{session_code:'',error:'LAUNCH_PARAMS_INVALID'}:{session_code:code,...(token?{marketplace_token:token}:{})};
}
