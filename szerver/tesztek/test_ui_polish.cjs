const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../alkalmazas/statikus/alkalmazas.js'), 'utf8');
function declaration(name) {
  let start = source.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, name);
  if (source.slice(start - 6, start) === 'async ') start -= 6;
  const end = source.indexOf('\n}\n', start);
  assert.notEqual(end, -1, name);
  return source.slice(start, end + 3);
}
function deferred() { let resolve, reject; const promise = new Promise((a,b) => {resolve=a;reject=b;}); return {promise,resolve,reject}; }
function context(extra={}) {
  const c=vm.createContext({state:{module:'settings',project:{id:1},navigationVersion:0,viewRenderVersion:0},console:{time(){},timeEnd(){},info(){},debug(){}},...extra});
  vm.runInContext(declaration('beginViewRender')+declaration('viewRenderIsCurrent'),c);
  return c;
}
test('a newer render of the same module invalidates the previous result',()=>{
  const c=context(); const old=c.beginViewRender('settings'); const next=c.beginViewRender('settings');
  assert.equal(c.viewRenderIsCurrent(old),false); assert.equal(c.viewRenderIsCurrent(next),true);
});
test('switching the project invalidates an in-flight render',()=>{
  const c=context(); const old=c.beginViewRender('settings'); c.state.project={id:2};
  assert.equal(c.viewRenderIsCurrent(old),false);
});
test('a refresh callback from a previous module cannot start a new render',()=>{
  const c=context(); c.state.module='finance'; assert.equal(c.beginViewRender('settings'),null);
});
test('the actual settings renderer discards a late response before touching the DOM',async()=>{
  const data=deferred(); const c=context({api:()=>data.promise,$(){throw Error('stale DOM mutation');}});
  vm.runInContext(declaration('renderSettings'),c);
  const work=c.renderSettings(); c.state.module='finance'; c.state.navigationVersion++;
  data.resolve({}); await work;
});
test('the actual schedule renderer also checks its second asynchronous response',async()=>{
  const timeline=deferred(),requested=deferred();
  const c=context({state:{module:'schedule',project:{id:1},navigationVersion:0,viewRenderVersion:0,scheduleView:'gantt',scheduleFinancialPhase:null,scheduleTimeline:null},toQuery:()=>'',api:(url)=>{
    if(url.includes('/timeline')) {requested.resolve();return timeline.promise;}
    return Promise.resolve(url.endsWith('/settings')?{}:[]);
  },$(){throw Error('stale DOM mutation');}});
  vm.runInContext(declaration('renderSchedule'),c);
  const work=c.renderSchedule(); await requested.promise;
  c.state.module='subcontractors'; c.state.navigationVersion++; timeline.resolve({rows:[]}); await work;
  assert.equal(c.state.scheduleTimeline,null);
});
test('the actual subcontractor renderer ignores a late response',async()=>{
  const data=deferred(); const c=context({api:()=>data.promise,$(){throw Error('stale DOM mutation');}});
  c.state.module='subcontractors'; vm.runInContext(declaration('renderSubcontractors'),c);
  const work=c.renderSubcontractors(); c.state.module='settings'; c.state.navigationVersion++;
  data.resolve({}); await work;
});
test('a late module error cannot replace the newly selected page',async()=>{
  const old=deferred(); let content='',header='';
  const noop=()=>{};
  const c=context({moduleLabels:{settings:['Data',''],schedule:['Schedule','']},hasPermission:()=>true,$$:()=>[],
    $:()=>({set innerHTML(v){content=v;}}),setHeader:v=>{header=v;},loading:()=>{content='loading';},
    beginPerformanceScope:()=>({}),endPerformanceScope:noop,toast:()=>{throw Error('stale toast');},empty:v=>v,
    renderSettings:()=>old.promise,renderSchedule:async()=>{content='schedule';},renderDisciplines:noop,
    renderSubcontractors:noop,renderFinance:noop,renderEngagements:noop,renderAdmin:noop});
  vm.runInContext(declaration('selectModule'),c);
  const first=c.selectModule('settings'); await c.selectModule('schedule');
  old.reject(Error('old request failed')); await first;
  assert.equal(content,'schedule'); assert.equal(header,'Schedule');
});
function floating(stored=null,storageFailure=false) {
  const listeners={},windowListeners={},classes=new Set(); let captured=null,toggles=0,open=false;
  const button={style:{},classList:{add:x=>classes.add(x),remove:x=>classes.delete(x)},
    addEventListener:(name,fn)=>listeners[name]=fn,setPointerCapture:id=>{captured=id;},
    hasPointerCapture:id=>captured===id,releasePointerCapture:()=>{captured=null;}};
  const storage=new Map(stored===null?[]:[['pc.ai-button-position.v1',stored]]);
  const c=vm.createContext({$:()=>button,state:{aiAssistant:{open:false}},window:{innerWidth:1000,innerHeight:700,addEventListener:(n,f)=>windowListeners[n]=f},
    localStorage:{getItem:k=>{if(storageFailure)throw Error('blocked');return storage.get(k)??null;},setItem:(k,v)=>{if(storageFailure)throw Error('blocked');storage.set(k,v);}},
    setAIAssistantOpen:v=>{open=v;c.state.aiAssistant.open=v;toggles++;}});
  vm.runInContext(declaration('clampAssistantPosition')+declaration('wireAIFloatingButton'),c); c.wireAIFloatingButton();
  const emit=(name,extra={})=>listeners[name]({button:0,isPrimary:true,pointerId:1,clientX:960,clientY:660,detail:1,preventDefault(){},...extra});
  return {c,button,emit,storage,windowListeners,get toggles(){return toggles;},get open(){return open;}};
}
test('an ordinary pointer tap opens the assistant',()=>{
  const f=floating(); f.emit('pointerdown'); f.emit('pointerup'); f.emit('click'); assert.equal(f.open,true);
});
test('dragging moves and saves the circle without opening it',()=>{
  const f=floating(); f.emit('pointerdown'); f.emit('pointermove',{clientX:760,clientY:460}); f.emit('pointerup'); f.emit('click');
  assert.equal(f.toggles,0); assert.equal(f.button.style.left,'732px'); assert.equal(f.button.style.top,'432px');
  const saved=f.storage.get('pc.ai-button-position.v1'); const reloaded=floating(saved);
  assert.equal(reloaded.button.style.left,f.button.style.left); assert.equal(reloaded.button.style.top,f.button.style.top);
});
test('a normal tap after a drag still opens the assistant',()=>{
  const f=floating(); f.emit('pointerdown'); f.emit('pointermove',{clientX:760}); f.emit('pointerup'); f.emit('click');
  f.emit('pointerdown'); f.emit('pointerup'); f.emit('click'); assert.equal(f.toggles,1);
});
test('pointer cancellation cleans up dragging and prevents an accidental click',()=>{
  const f=floating(); f.emit('pointerdown'); f.emit('pointermove',{clientX:760}); f.emit('pointercancel'); f.emit('click'); assert.equal(f.toggles,0);
});
test('keyboard activation is not swallowed after a drag',()=>{
  const f=floating(); f.emit('pointerdown'); f.emit('pointermove',{clientX:760}); f.emit('pointerup'); f.emit('click',{detail:0}); assert.equal(f.open,true);
});
test('Alt arrows move the circle and Alt Home resets it',()=>{
  const f=floating(); f.emit('keydown',{altKey:true,key:'ArrowLeft'}); assert.equal(f.button.style.left,'916px');
  f.emit('keydown',{altKey:true,key:'Home'}); assert.equal(f.button.style.left,'932px');
});
test('resizing keeps a stored circle inside the new viewport',()=>{
  const f=floating(); f.c.window.innerWidth=320; f.c.window.innerHeight=480; f.windowListeners.resize();
  assert.equal(f.button.style.left,'252px'); assert.equal(f.button.style.top,'354px');
});
test('malformed or unavailable preference storage does not break the assistant',()=>{
  assert.equal(floating('{bad').button.style.left,'932px');
  const f=floating(null,true); f.emit('keydown',{altKey:true,key:'ArrowLeft'}); assert.equal(f.button.style.left,'916px');
});
