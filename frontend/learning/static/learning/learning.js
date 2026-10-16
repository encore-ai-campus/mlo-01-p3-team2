(() => {
  'use strict';
  const panel = document.getElementById('learningDialog');
  const $ = (id) => panel.querySelector('#' + id);
  const labels = {multiple_choice: 'Python 객관식', fill_blank: '코드 빈칸 채우기'};
  const levels = {beginner: '초급', intermediate: '중급', advanced: '고급'};
  const state = {
    screen: 'home', sessionId: null, questionType: null, difficulty: null, subject:'python', pendingSubmission:null,
    currentOrder: 1, totalQuestions: 0, question: null, selectedAnswer: null, selectedChoiceUuid: null,
    questionFinalized: false, attemptCount: 0, maxAttempts: 3, feedback: null, busy: false, authenticated: false,
    csrfToken: null, retryAction: null, disabledControls: [],
  };

  function newSubmissionUuid(){
    if(typeof crypto.randomUUID==='function')return crypto.randomUUID();
    const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
    const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
  }

  class ApiError extends Error {
    constructor(status, code, message) { super(message); this.status = status; this.code = code; }
  }

  function csrfCookie() {
    const cookie = document.cookie.split('; ').find(item => item.startsWith('campus_csrftoken='));
    return cookie ? decodeURIComponent(cookie.substring('campus_csrftoken='.length)) : null;
  }

  async function request(path, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    let response;
    try {
      response = await fetch(`/api/learning/${path}`, {
        ...options, credentials: 'same-origin', cache: 'no-store', signal: controller.signal,
      });
      const data = await response.json();
      if (!response.ok) throw new ApiError(response.status, data.error, data.message);
      return data;
    } catch (error) {
      if (error instanceof ApiError) throw error;
      throw new ApiError(0, 'network_error', '서버에 연결할 수 없습니다. 잠시 후 다시 시도해주세요.');
    } finally { clearTimeout(timer); }
  }

  async function fetchCsrf() {
    await request('csrf/');
    state.csrfToken = csrfCookie();
    if (!state.csrfToken) throw new ApiError(403, 'csrf_failed');
    state.authenticated = true;
    $('auth-notice').hidden = true;
  }

  async function post(path, data = {}) {
    if (!state.csrfToken) await fetchCsrf();
    return request(path, {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRFToken': state.csrfToken}, body: JSON.stringify(data)});
  }

  const createSession = () => post('sessions/', {subject:state.subject, question_type: state.questionType, difficulty: state.difficulty});
  const fetchQuestion = (order) => request(`sessions/${state.sessionId}/questions/${order}/`);
  const submitAnswer = (answer) => post(`sessions/${state.sessionId}/questions/${state.currentOrder}/answers/`, {answer, submission_request_uuid:state.pendingSubmission.uuid, choice_uuid:state.pendingSubmission.choiceUuid ?? null});
  const completeSession = () => post(`sessions/${state.sessionId}/complete/`);
  const fetchSessionResult = () => request(`sessions/${state.sessionId}/`);

  function showBalance(balance) {
    if (!Number.isSafeInteger(balance) || balance < 0) return;
    $('learning-wallet').textContent = `보유 ${balance.toLocaleString('ko-KR')}P`;
    window.dispatchEvent(new CustomEvent('campus:wallet', {detail: {balance}}));
  }

  function refreshBalance() {
    return request('wallet/').then(data => showBalance(data.balance)).catch(() => {});
  }

  function clearError() {
    $('error-message').hidden = true;
    $('error-retry').hidden = true;
    state.retryAction = null;
  }

  function showError(error, retryAction = null) {
    let message = error.message || '요청을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.';
    if (error.status === 401) {
      message = '로그인이 필요합니다.';
      state.authenticated = false; state.csrfToken = null;
      $('auth-notice').hidden = false;
    } else if (error.status === 403) {
      message = '요청 권한 또는 CSRF 문제가 있습니다. 로그인 상태를 확인한 뒤 다시 시도해주세요.';
      state.csrfToken = null;
    } else if (error.status === 404) {
      message = '세션 또는 문제를 찾을 수 없습니다.';
    } else if (['empty_question_pool','insufficient_question_pool'].includes(error.code)) {
      message = '선택한 과목·유형·난이도에 활성 문제 10개 이상이 필요합니다.';
    }
    $('error-text').textContent = message;
    $('error-message').hidden = false;
    // Never automatically resend a POST after an uncertain network response.
    state.retryAction = retryAction;
    $('error-retry').hidden = !retryAction;
  }

  function setBusy(busy, message = '') {
    state.busy = busy;
    $('learning-app').setAttribute('aria-busy', String(busy));
    $('loading-message').hidden = !busy;
    $('loading-message').textContent = message;
    if (busy) {
      state.disabledControls = [...document.querySelectorAll('#learning-app button, #learning-app input')].map(el => [el, el.disabled]);
      state.disabledControls.forEach(([el]) => { el.disabled = true; });
    } else {
      state.disabledControls.forEach(([el, disabled]) => { el.disabled = disabled; });
      state.disabledControls = [];
    }
  }

  async function run(message, action, retryAction = null) {
    if (state.busy) return;
    clearError(); setBusy(true, message);
    try { await action(); }
    catch (error) { showError(error, retryAction); }
    finally { setBusy(false); }
  }

  function showScreen(screen, focusId) {
    state.screen = screen;
    for (const name of ['home', 'difficulty', 'question', 'result']) $(name + '-screen').hidden = name !== screen;
    $('learning-app').dataset.theme = state.questionType || '';
    panel.dataset.contentType=state.questionType || '';
    $('popup-title').textContent=screen==='result'?'학습 결과':labels[state.questionType] || 'Python 학습교실';
    if (focusId) $(focusId).focus({preventScroll: true});
  }

  function showHome() {
    clearError();
    Object.assign(state, {sessionId: null, questionType: null, difficulty: null, currentOrder: 1,
      totalQuestions: 0, question: null, selectedAnswer: null, selectedChoiceUuid: null, questionFinalized: false, attemptCount: 0, feedback: null});
    panel.close();
  }

  function showDifficulty(type) {
    if (state.busy) return;
    clearError();
    state.questionType = type;
    $('difficulty-title').textContent = labels[type];
    showScreen('difficulty', 'difficulty-title');
  }

  function updateProgress() {
    const finished = Math.max(0, state.currentOrder - 1 + (state.questionFinalized ? 1 : 0));
    const percentage = state.totalQuestions ? Math.round(finished / state.totalQuestions * 100) : 0;
    $('progress-fill').style.width = `${percentage}%`;
    $('question-progress').setAttribute('aria-valuenow', String(percentage));
    $('progress-caption').textContent = `${finished}문제 확정 · ${percentage}%`;
  }

  function showQuestion(data, order) {
    state.currentOrder = order;
    state.totalQuestions = data.total_questions;
    state.question = data.question;state.pendingSubmission=null;
    const pendingKey=`learning:submission:${state.sessionId}:${order}`;
    const savedPending=sessionStorage.getItem(pendingKey);
    if(data.is_finalized)sessionStorage.removeItem(pendingKey);
    else if(savedPending){try{state.pendingSubmission=JSON.parse(savedPending);}catch{sessionStorage.removeItem(pendingKey);}}
    state.selectedAnswer = null; state.selectedChoiceUuid = null;
    state.questionFinalized = data.is_finalized;
    state.attemptCount = data.attempt_count;
    state.maxAttempts = data.max_attempts;
    state.feedback = null;
    $('question-context').textContent = `${labels[state.questionType]} · ${levels[state.difficulty]}`;
    $('question-count').textContent = `${order} / ${state.totalQuestions}`;
    $('challenge-count').textContent = `도전 ${Math.min(state.maxAttempts, state.attemptCount + 1)} / ${state.maxAttempts}`;
    $('question-label').textContent = `QUESTION ${String(order).padStart(2, '0')}`;
    $('question-title').textContent = data.question.question_text;
    $('question-code').textContent = data.question.code_snippet || '';
    $('code-area').hidden = !data.question.code_snippet;
    const isMcq = data.question.question_type === 'multiple_choice';
    $('choices-fieldset').hidden = !isMcq;
    $('choices-fieldset').disabled = false;
    $('blank-answer-area').hidden = isMcq;
    $('blank-answer').value = '';
    $('blank-answer').disabled = false;
    $('choice-list').replaceChildren();
    if (isMcq) {
      for (const choice of data.question.choices) {
        const label = document.createElement('label'); label.className = 'choice-label';
        const input = document.createElement('input'); input.type = 'radio'; input.name = 'choice'; input.value = choice.choice_text;
        input.addEventListener('change', () => { state.selectedAnswer = input.value; state.selectedChoiceUuid = choice.choice_uuid; clearError(); });
        const number = document.createElement('span'); number.className = 'choice-number'; number.textContent = String(choice.choice_no).padStart(2, '0');
        const text = document.createElement('span'); text.textContent = choice.choice_text;
        label.append(input, number, text); $('choice-list').append(label);
      }
    }
    $('answer-hint').textContent=state.subject==='sql'?'SQL 키워드의 대소문자와 불필요한 공백은 허용합니다. 문자열 리터럴은 그대로 입력하세요.':'코드의 대소문자를 확인해주세요.';
    $('code-area').querySelector('.code-header span').textContent=state.subject==='sql'?'SQL':'Python';
    if(state.pendingSubmission){$('blank-answer').value=state.pendingSubmission.answer;state.selectedAnswer=state.pendingSubmission.answer;state.selectedChoiceUuid=state.pendingSubmission.choiceUuid ?? null;for(const input of $('choice-list').querySelectorAll('input'))input.checked=input.value===state.pendingSubmission.answer;}
    $('answer-form').hidden = false;
    $('feedback').hidden = true;
    $('retry-answer-button').hidden = true;
    $('next-button').hidden = true;
    updateProgress();
    showScreen('question', 'question-title');
    if (data.is_finalized) showFeedback({...data, is_correct: data.outcome !== 'incorrect', attempt_no: data.attempt_count, explanation: ''});
  }

  async function loadQuestion(order) {
    const data = await fetchQuestion(order);
    if (data.question.subject !== state.subject || data.question.question_type !== state.questionType || data.question.difficulty !== state.difficulty) {
      throw new ApiError(409, 'content_mismatch', '학습 콘텐츠가 일치하지 않습니다. 학습 홈에서 다시 시작해주세요.');
    }
    showQuestion(data, order);
  }

  function retryQuestionLoad(order) {
    return () => run('문제를 불러오는 중...', () => loadQuestion(order), retryQuestionLoad(order));
  }

  function beginSession(difficulty) {
    if (state.busy) return;
    state.difficulty = difficulty;
    run('학습을 준비하는 중...', async () => {
      const session = await createSession();
      showBalance(session.points_summary?.wallet_balance);
      state.sessionId = session.session_id;sessionStorage.setItem(`learning:${state.subject}:${state.questionType}`,String(session.session_id));
      state.totalQuestions = session.total_questions;
      state.currentOrder = 1;
      state.question = null;
      $('question-context').textContent = `${labels[state.questionType]} · ${levels[state.difficulty]}`;
      $('question-count').textContent = `1 / ${session.total_questions}`;
      $('question-title').textContent = '첫 문제를 준비하고 있어요.';
      $('answer-form').hidden = true; $('feedback').hidden = true;
      $('code-area').hidden = true; $('retry-answer-button').hidden = true; $('next-button').hidden = true;
      state.questionFinalized = false; state.attemptCount = 0; updateProgress(); showScreen('question');
      try { await loadQuestion(1); }
      catch (error) { showError(error, retryQuestionLoad(1)); }
    });
  }

  function showFeedback(data) {
    $('popup-title').textContent='정답 확인';
    state.feedback = data;
    state.questionFinalized = data.is_finalized;
    state.attemptCount = data.attempt_count;
    state.maxAttempts = data.max_attempts;
    $('challenge-count').textContent = `도전 ${Math.min(state.maxAttempts, data.attempt_no)} / ${state.maxAttempts}`;
    $('answer-form').hidden = true;
    $('feedback').classList.toggle('wrong', !data.is_correct);
    $('feedback-icon').textContent = data.is_correct ? '✓' : '!';
    $('feedback-title').textContent = data.is_correct ? '정답입니다!' : data.is_finalized ? '3회 모두 틀렸습니다.' : data.remaining_attempts === 1 ? '오답입니다. 마지막 기회가 남았습니다.' : '오답입니다. 다시 도전해보세요.';
    $('feedback-answer').textContent = data.answer_revealed ? `정답: ${formatAnswer(data)}` : '';
    $('feedback-answer').hidden = !data.answer_revealed;
    $('choices-fieldset').disabled = data.is_finalized;
    $('blank-answer').disabled = data.is_finalized;
    $('feedback-explanation').textContent = data.answer_revealed ? (data.explanation || '') : '';
    $('feedback-explanation').hidden = !data.answer_revealed || !data.explanation;
    $('attempt-text').textContent = data.is_correct ? (data.outcome === 'first_try_correct' ? '첫 시도 정답' : '재시도 후 정답') : data.is_finalized ? '이번 문제는 최종 오답으로 처리됩니다.' : `남은 기회: ${data.remaining_attempts}회`;
    const points = data.points;
    $('feedback-points').hidden = !points;
    $('feedback-points').textContent = points?.status === 'granted' ? `+${points.granted_points}P 적립 완료` : points?.status === 'not_connected' ? '이전 학습 기록 · 포인트 지급 내역 없음' : '이번 답안 적립 0P';
    showBalance(points?.balance_after);
    $('feedback').hidden = false;
    $('retry-answer-button').hidden = data.is_finalized;
    $('next-button').hidden = !data.is_finalized;
    $('next-button').textContent = state.currentOrder === state.totalQuestions ? '학습 완료' : '다음 문제 →';
    updateProgress();
  }

  function handleSubmit(event) {
    event.preventDefault();
    if (state.busy || !state.question || state.feedback) return;
    const answer = state.questionType === 'multiple_choice' ? state.selectedAnswer : $('blank-answer').value;
    if (!answer || !answer.trim()) {
      showError(new Error(state.questionType === 'multiple_choice' ? '답을 선택해주세요.' : '답을 입력해주세요.'));
      if (state.questionType === 'fill_blank') $('blank-answer').focus();
      else $('choice-list').querySelector('input')?.focus();
      return;
    }
    if(!state.pendingSubmission){state.pendingSubmission={answer,uuid:newSubmissionUuid(),choiceUuid:state.questionType==='multiple_choice'?state.selectedChoiceUuid:null};sessionStorage.setItem(`learning:submission:${state.sessionId}:${state.currentOrder}`,JSON.stringify(state.pendingSubmission));}
    if(state.pendingSubmission.answer!==answer){showError(new Error('이전 제출의 처리 여부를 먼저 확인해주세요. 같은 답안을 다시 제출하면 중복 저장되지 않습니다.'));return;}
    run('답안을 제출하는 중...', async () => {
      try { showFeedback(await submitAnswer(answer));sessionStorage.removeItem(`learning:submission:${state.sessionId}:${state.currentOrder}`);state.pendingSubmission=null; await refreshBalance(); }
      catch (error) {
        if (error.code === 'question_finalized' || error.code === 'attempt_limit_reached') await loadQuestion(state.currentOrder);
        else {if(error.status&&error.status<500){state.pendingSubmission=null;sessionStorage.removeItem(`learning:submission:${state.sessionId}:${state.currentOrder}`);}throw error;}
      }
    });
  }

  function retryAnswer() {
    if (state.busy || state.questionFinalized) return;
    clearError(); state.feedback = null; state.selectedAnswer = null;state.selectedChoiceUuid=null;state.pendingSubmission=null;
    $('feedback').hidden = true; $('retry-answer-button').hidden = true;
    $('answer-hint').textContent=state.subject==='sql'?'SQL 키워드의 대소문자와 불필요한 공백은 허용합니다. 문자열 리터럴은 그대로 입력하세요.':'코드의 대소문자를 확인해주세요.';
    $('code-area').querySelector('.code-header span').textContent=state.subject==='sql'?'SQL':'Python';
    $('answer-form').hidden = false; $('blank-answer').value = '';
    $('choice-list').querySelectorAll('input').forEach(input => { input.checked = false; });
    $('challenge-count').textContent = `도전 ${Math.min(state.maxAttempts, state.attemptCount + 1)} / ${state.maxAttempts}`;
    if (state.questionType === 'fill_blank') $('blank-answer').focus();
    else $('choice-list').querySelector('input')?.focus();
  }

  function formatAnswer(data) {
    const symbols = ['', '①', '②', '③', '④'];
    return `${symbols[data.correct_choice_no] || ''} ${data.correct_answer ?? ''}`.trim();
  }

  function renderReview(items) {
    $('review-list').replaceChildren();
    $('wrong-review').hidden = true;
    $('review-button').hidden = !items.length;
    for (const item of items) {
      const card = document.createElement('article'); card.className = 'review-card';
      const heading = document.createElement('h4'); heading.textContent = `문제 ${item.question_order}: ${item.question_text}`;
      card.append(heading);
      if (item.code_snippet) {
        const code = document.createElement('pre'); code.textContent = item.code_snippet; card.append(code);
      }
      for (const [label, text] of [['내 마지막 답', item.submitted_answer], ['정답', formatAnswer(item)], ['해설', item.explanation]]) {
        const line = document.createElement('p'); line.textContent = `${label}: ${text || ''}`; card.append(line);
      }
      $('review-list').append(card);
    }
  }

  function showResult(data) {
    renderReview(data.wrong_questions || []);
    $('result-title').textContent=data.passed===null?'학습 완료!':data.passed?'학습 완료 · 통과':'학습 완료 · 미통과';
    const resultNote=panel.querySelector('.result-note');
    resultNote.lastChild.textContent=data.completed_at?`완료: ${new Date(data.completed_at).toLocaleString('ko-KR')}`:'세 번의 도전, 오늘의 배움을 기록했어요.';
    sessionStorage.removeItem(`learning:${state.subject}:${state.questionType}`);
    $('result-context').textContent = `${labels[data.question_type]} · ${levels[data.difficulty]}`;
    $('result-score').textContent = `${data.correct_count} / ${data.total_questions}`;
    $('result-accuracy').textContent = `${data.final_accuracy}%`;
    $('result-first').textContent = `${data.first_try_correct_count}문제`;
    $('result-retry').textContent = `${data.retry_correct_count}문제`;
    $('result-incorrect').textContent = `${data.final_incorrect_count}문제`;
    $('result-total').textContent = `총 ${data.total_questions}문제`;
    $('result-rate').textContent = `${data.final_accuracy}%`;
    const points=data.points_summary;
    $('result-points').textContent=points?`이번 학습 ${points.granted_total}P 적립${points.unpaid_legacy_count?' · 이전 미지급 기록 포함':''}`:'포인트 내역을 확인할 수 없습니다.';
    showBalance(points?.wallet_balance);
    $('score-ring').style.setProperty('--score-angle', `${Math.max(0, Math.min(100, data.final_accuracy)) * 3.6}deg`);
    showScreen('result', 'result-title');
  }

  function nextQuestion() {
    if (state.busy || !state.questionFinalized) return;
    if (state.currentOrder === state.totalQuestions) {
      const finish = () => run('학습 결과를 정리하는 중...', async () => {
        await completeSession();
        showResult(await fetchSessionResult());
      }, finish);
      finish();
    } else {
      const order = state.currentOrder + 1;
      run('다음 문제를 불러오는 중...', () => loadQuestion(order), retryQuestionLoad(order));
    }
  }

  function requestHome() {
    if (state.busy) return;
    if (state.sessionId && state.screen === 'question') $('leave-dialog').showModal();
    else showHome();
  }

  document.querySelectorAll('[data-content]').forEach(button => button.addEventListener('click', () => showDifficulty(button.dataset.content)));
  document.querySelectorAll('[data-difficulty]').forEach(button => button.addEventListener('click', () => beginSession(button.dataset.difficulty)));
  $('answer-form').addEventListener('submit', handleSubmit);
  $('retry-answer-button').addEventListener('click', retryAnswer);
  $('next-button').addEventListener('click', nextQuestion);
  $('home-button').addEventListener('click', requestHome);
  $('review-button').addEventListener('click', () => {
    $('wrong-review').hidden = !$('wrong-review').hidden;
    if (!$('wrong-review').hidden) $('review-title').focus();
  });
  $('result-home-button').addEventListener('click', showHome);
  $('restart-button').addEventListener('click', () => beginSession(state.difficulty));
  $('error-retry').addEventListener('click', () => state.retryAction?.());
  $('leave-cancel').addEventListener('click', () => $('leave-dialog').close());
  $('leave-confirm').addEventListener('click', () => { $('leave-dialog').close(); showHome(); });
  $('blank-answer').addEventListener('input', clearError);
  window.addEventListener('beforeunload', event => {
    if (state.sessionId && state.screen === 'question') { event.preventDefault(); event.returnValue = ''; }
  });

  panel.addEventListener('cancel', event => { event.preventDefault(); requestHome(); });
  window.CampusLearning = {
    get blocking() { return panel.open; },
    open(type, subject='python') {
      if (!Object.hasOwn(labels, type) || !['python','sql'].includes(subject) || state.busy || panel.open) return;
      state.subject=subject;
      const display=subject==='sql'?'SQL':'Python';
      labels.multiple_choice=`${display} 객관식`;labels.fill_blank=subject==='sql'?'SQL 코드 빈칸 채우기':'코드 빈칸 채우기';
      const descriptions=$('difficulty-screen').querySelectorAll('.difficulty-option small');
      const texts=subject==='sql'?['SQL 기본 문법','조회와 집계','심화 SQL']:['Python 기본 문법','자료구조와 함수','심화 Python'];
      descriptions.forEach((node,index)=>{node.textContent=texts[index];});
      if(!window.CampusClassroomMap)document.title=`${display} Learning Room`;
      panel.setAttribute('aria-label',`${display} 학습 패널`);
      panel.showModal(); showDifficulty(type);
      const prepare = () => run('로그인과 진행 상태를 확인하는 중...',async()=>{
        await fetchCsrf();
        const content = await post('content-open/', {subject, question_type:type});
        showBalance(content.wallet_balance);
        descriptions.forEach((node,index)=>{const level=['beginner','intermediate','advanced'][index];node.textContent=`${texts[index]} · 정답 ${content.points_by_difficulty[level]}P`;});
        const saved=sessionStorage.getItem(`learning:${subject}:${type}`);
        if(!saved)return;
        let session;
        try{session=await request(`sessions/${saved}/`);}catch(error){if(error.status===404){sessionStorage.removeItem(`learning:${subject}:${type}`);return;}throw error;}
        if(session.completed_at){sessionStorage.removeItem(`learning:${subject}:${type}`);return;}
        state.sessionId=session.session_id;state.difficulty=session.difficulty;
        const next=session.questions.find(q=>!q.is_finalized);
        await loadQuestion(next?next.question_order:session.total_questions);
      }, prepare);
      prepare();
    },
  };
})();
