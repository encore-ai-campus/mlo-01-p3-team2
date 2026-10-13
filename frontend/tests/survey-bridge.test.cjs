const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function fixture(){
  const properties = new Map(), items=[], storedResponses=[];
  let formReads=0, submittedResponses=0;
  const formId='117DNOSfnLfgmBkv-DkWruqjXKeuFQe--UbeeEg2L34c';
  const formUrl='https://docs.google.com/forms/d/e/1FAIpQLSf4dkDBcM-7uXtJNXjgsYUsstKRHDPUQ_M3WfCaZne_CUcIEA/viewform';
  function item(){
    const value={title:'',id:202,index:0};
    value.getTitle=()=>value.title;value.getId=()=>value.id;value.getIndex=()=>0;value.asTextItem=()=>value;
    value.setTitle=v=>{value.title=v;return value;};
    for(const method of ['setHelpText','setRequired','setValidation'])value[method]=()=>value;
    value.createResponse=answer=>({item:value,answer});return value;
  }
  const form={getId:()=>formId,getPublishedUrl:()=>formUrl,getItems:()=>items,moveItem(){},setAllowResponseEdits(){},setConfirmationMessage(){},isPublished:()=>true,isAcceptingResponses:()=>true,
    addTextItem(){const value=item();items.push(value);return value;},getItemById(id){return items.find(i=>i.getId()===id);},
    createResponse(){return {withItemResponse(answer){return {toPrefilledUrl:()=>formUrl+'?usp=pp_url&entry.123456789='+answer.answer,submit(){submittedResponses++;}};}};},
    getResponses(since){formReads++;return storedResponses.filter(r=>r.getTimestamp()>=since);}};
  const output=value=>({text:value,setMimeType(){return this;}});
  const validation={requireTextMatchesPattern(){return this;},setHelpText(){return this;},build(){return {};}};
  const context={console:{log(){}},PropertiesService:{getScriptProperties:()=>({getProperty:key=>properties.get(key)||null,setProperties(values){for(const [k,v] of Object.entries(values))properties.set(k,v);}})},
    LockService:{getScriptLock:()=>({waitLock(){},releaseLock(){}})},Utilities:{getUuid:()=> '12345678-1234-1234-1234-123456789abc'},
    FormApp:{openById(id){assert.equal(id,formId);return form;},ItemType:{TEXT:'text'},createTextValidation:()=>validation},
    ContentService:{createTextOutput:output,MimeType:{JSON:'json'}}};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../../backend/scripts/GOOGLE_RAFFLE_SURVEY.gs'),'utf8'),context);
  function post(request){return JSON.parse(context.doPost({postData:{contents:JSON.stringify(request)}}).text);}
  function response(token,id,when,answer='private survey answer'){
    const saved={getId:()=>id,getTimestamp:()=>new Date(when),getItemResponses:()=>[{getItem:()=>({getId:()=>202}),getResponse:()=>token},{getItem:()=>({getId:()=>888}),getResponse:()=>answer}]};
    storedResponses.push(saved);return saved;
  }
  return {context,properties,items,post,response,get reads(){return formReads;},get submitted(){return submittedResponses;}};
}

test('setup adds one token field, reuses its key, and never submits a form response',()=>{
  const f=fixture(),first=f.context.setupRaffleSurvey(),second=f.context.setupRaffleSurvey();
  assert.equal(f.items.length,1);assert.equal(first.accessKey,second.accessKey);assert.equal(first.accessKey.length,64);
  assert.equal(first.tokenParameter,'entry.123456789');assert.equal(f.submitted,0);
});
test('GET and POST with the wrong key return no metadata or responses',()=>{
  const f=fixture();f.context.setupRaffleSurvey();
  assert.equal(JSON.parse(f.context.doGet().text).ok,false);
  const result=f.post({version:1,action:'responses',accessKey:'wrong',tokens:[]});
  assert.equal(result.ok,false);assert.equal(result.responses,undefined);assert.equal(result.formId,undefined);assert.equal(f.reads,0);
});
test('authorized polling returns only requested tokens and never survey answer text',()=>{
  const f=fixture(),config=f.context.setupRaffleSurvey(),token='A'.repeat(43),other='B'.repeat(43),now=Date.now();
  f.response(token,'mine',now-1000);f.response(other,'other',now-2000);
  const result=f.post({version:1,action:'responses',accessKey:config.accessKey,tokens:[token],since:new Date(now-5000).toISOString()});
  assert.equal(result.ok,true);assert.equal(result.responses.length,1);assert.equal(result.responses[0].responseId,'mine');
  assert.equal(JSON.stringify(result).includes('private survey answer'),false);assert.equal(JSON.stringify(result).includes(config.accessKey),false);
});
test('duplicate form submissions use the earliest response for the same token',()=>{
  const f=fixture(),config=f.context.setupRaffleSurvey(),token='A'.repeat(43),now=Date.now();
  f.response(token,'later',now-1000);f.response(token,'first',now-3000);
  const result=f.post({version:1,action:'responses',accessKey:config.accessKey,tokens:[token],since:new Date(now-5000).toISOString()});
  assert.equal(result.responses.length,1);assert.equal(result.responses[0].responseId,'first');
});
test('invalid tokens and invalid dates cannot read form responses',()=>{
  const f=fixture(),config=f.context.setupRaffleSurvey();
  for(const extra of [{tokens:['bad'],since:new Date().toISOString()},{tokens:['A'.repeat(43)],since:'invalid'},{tokens:Array(101).fill('A'.repeat(43)),since:new Date().toISOString()}]){
    assert.equal(f.post({version:1,action:'responses',accessKey:config.accessKey,...extra}).ok,false);
  }
  assert.equal(f.reads,0);
});
