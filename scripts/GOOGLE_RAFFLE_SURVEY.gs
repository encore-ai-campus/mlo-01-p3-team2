/**
 * Run setupRaffleSurvey in the Google account that owns the existing survey.
 * Deploy as a web app: execute as Me, access Anyone. The private access key
 * is checked before any form metadata or submission is returned.
 * No public platform URL, form submission trigger, or Sheets credentials needed.
 * Docs: https://developers.google.com/apps-script/guides/web
 */
const RAFFLE_FORM_ID = '117DNOSfnLfgmBkv-DkWruqjXKeuFQe--UbeeEg2L34c';
const RAFFLE_TOKEN_TITLE = '이벤트 참가 확인 코드';

function setupRaffleSurvey() {
  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const properties = PropertiesService.getScriptProperties();
    const form = FormApp.openById(RAFFLE_FORM_ID);
    const savedItem = properties.getProperty('RAFFLE_TOKEN_ITEM_ID');
    let item = savedItem ? form.getItems(FormApp.ItemType.TEXT).find(x => String(x.getId()) === savedItem) : null;
    if (!item) item = form.getItems(FormApp.ItemType.TEXT).find(x => x.getTitle() === RAFFLE_TOKEN_TITLE);
    item = item ? item.asTextItem() : form.addTextItem();
    item.setTitle(RAFFLE_TOKEN_TITLE).setHelpText('부저에서 자동 입력된 코드를 그대로 유지해 주세요. 설문 제출 후 이벤트 참가 명단에 자동 등록됩니다.').setRequired(true);
    item.setValidation(FormApp.createTextValidation().requireTextMatchesPattern('^[A-Za-z0-9_-]{43}$').setHelpText('플랫폼의 이벤트 부저에서 설문을 열어 주세요.').build());
    form.moveItem(item.getIndex(), 0);
    form.setAllowResponseEdits(false);
    form.setConfirmationMessage('설문 제출이 완료됐습니다. 플랫폼으로 돌아오면 잠시 후 이벤트 참가 명단에 자동 등록됩니다.');
    const sample = form.createResponse().withItemResponse(item.createResponse('R'.repeat(43))).toPrefilledUrl();
    const match = sample.match(/[?&](entry\.\d+)=R{43}(?:&|$)/);
    if (!match) throw new Error('참가 확인 코드 자동 입력 주소를 찾지 못했습니다.');
    let accessKey = properties.getProperty('RAFFLE_ACCESS_KEY');
    if (!accessKey) accessKey = (Utilities.getUuid() + Utilities.getUuid()).replace(/-/g, '');
    properties.setProperties({RAFFLE_FORM_ID:form.getId(), RAFFLE_TOKEN_ITEM_ID:String(item.getId()), RAFFLE_TOKEN_PARAMETER:match[1], RAFFLE_ACCESS_KEY:accessKey});
    console.log('설문 연결 준비 완료. 웹 앱으로 배포한 뒤 아래 연결 키를 플랫폼 관리자 설정에 입력하세요.');
    console.log('연결 키: ' + accessKey);
    console.log('설문 응답 주소: ' + form.getPublishedUrl());
    return {formUrl:form.getPublishedUrl(), tokenParameter:match[1], accessKey};
  } finally {
    lock.releaseLock();
  }
}

function raffleJson_(data) {
  return ContentService.createTextOutput(JSON.stringify(data)).setMimeType(ContentService.MimeType.JSON);
}

function raffleKeyMatches_(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length || b.length < 32) return false;
  let difference = 0;
  for (let i=0; i<b.length; i++) difference |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return difference === 0;
}

function doGet() {
  return raffleJson_({ok:false, error:'authentication_required'});
}

function doPost(e) {
  try {
    if (!e || !e.postData || e.postData.contents.length > 16384) return raffleJson_({ok:false, error:'invalid_request'});
    const request = JSON.parse(e.postData.contents);
    const properties = PropertiesService.getScriptProperties();
    if (!raffleKeyMatches_(request.accessKey, properties.getProperty('RAFFLE_ACCESS_KEY'))) return raffleJson_({ok:false, error:'unauthorized'});
    if (request.version !== 1 || !['info','responses'].includes(request.action)) return raffleJson_({ok:false, error:'invalid_request'});
    const formId = properties.getProperty('RAFFLE_FORM_ID'), itemId = properties.getProperty('RAFFLE_TOKEN_ITEM_ID'), tokenParameter = properties.getProperty('RAFFLE_TOKEN_PARAMETER');
    if (!formId || !itemId || !tokenParameter) return raffleJson_({ok:false, error:'setup_required'});
    const form = FormApp.openById(formId);
    form.getItemById(Number(itemId));
    // The platform delays a draw if this read boundary does not yet cover
    // the participation deadline. Survey answers never leave Google here.
    const checkedAt = new Date().toISOString();
    const result = {ok:true, version:1, formId, formUrl:form.getPublishedUrl(), tokenParameter, checkedAt, acceptingResponses:form.isPublished() && form.isAcceptingResponses()};
    if (request.action === 'info') return raffleJson_(result);
    if (!Array.isArray(request.tokens) || request.tokens.length > 100 || request.tokens.some(t => typeof t !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(t))) return raffleJson_({ok:false, error:'invalid_tokens'});
    const since = new Date(request.since);
    if (Number.isNaN(since.getTime())) return raffleJson_({ok:false, error:'invalid_date'});
    const wanted = new Set(request.tokens), earliest = new Map();
    form.getResponses(since).forEach(response => {
      const answer = response.getItemResponses().find(a => String(a.getItem().getId()) === itemId);
      const token = answer ? String(answer.getResponse()).trim() : '';
      if (!wanted.has(token)) return;
      const submittedAt = response.getTimestamp();
      if (submittedAt.toISOString() > checkedAt) return;
      const previous = earliest.get(token);
      if (!previous || submittedAt.toISOString() < previous.submittedAt) earliest.set(token, {token, responseId:response.getId(), submittedAt:submittedAt.toISOString()});
    });
    result.responses = [...earliest.values()];
    return raffleJson_(result);
  } catch (error) {
    return raffleJson_({ok:false, error:'survey_read_failed'});
  }
}
