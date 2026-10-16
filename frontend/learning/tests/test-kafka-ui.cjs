/* Run with Node and Playwright; API responses are isolated from the real server. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('playwright');

const learningRoot = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(learningRoot, 'templates/learning/panel.html'), 'utf8');
const script = fs.readFileSync(path.join(learningRoot, 'static/learning/learning.js'), 'utf8');
const styles = fs.readFileSync(path.join(learningRoot, 'static/learning/learning.css'), 'utf8');
const choiceId = 'd9c8bf8b-1aa5-4d45-9f15-78a7a486191a';

async function scenario(browser, subject, kind) {
  const context = await browser.newContext({viewport: {width: 1200, height: 850}});
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await context.addCookies([{name: 'campus_csrftoken', value: 'test-csrf', url: 'http://campus.test'}]);
  const requests = [];
  const answer = subject === 'sql' ? 'SELECT' : 'append';
  await page.route('http://campus.test/**', async route => {
    const request = route.request();
    const endpoint = new URL(request.url()).pathname;
    const body = request.postDataJSON();
    requests.push({endpoint, method: request.method(), body});
    if (endpoint === '/') {
      await route.fulfill({contentType: 'text/html', body: `<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>${styles}</style></head><body>${html}<script>${script}</script></body></html>`});
      return;
    }
    let data;
    if (endpoint.endsWith('/csrf/')) data = {detail: 'CSRF cookie set'};
    else if (endpoint.endsWith('/content-open/')) {
      assert.deepEqual(body, {subject, question_type: kind});
      data = {wallet_balance: 10, points_by_difficulty: {beginner: 20, intermediate: 50, advanced: 80}};
    } else if (endpoint.endsWith('/wallet/')) data = {balance: 30};
    else if (endpoint.endsWith('/answers/')) {
      const submissions = requests.filter(item => item.endpoint.endsWith('/answers/'));
      if (submissions.length === 1) {
        await route.abort('failed');
        return;
      }
      assert.deepEqual(submissions[0].body, body, 'An uncertain retry must keep its request ID and selected choice');
      assert.equal(body.answer, answer);
      assert.equal(body.choice_uuid, kind === 'multiple_choice' ? choiceId : null);
      assert.match(body.submission_request_uuid, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
      data = {is_correct: true, is_finalized: true, attempt_no: 1, attempt_count: 1,
        max_attempts: 3, outcome: 'first_try_correct', remaining_attempts: 0,
        answer_revealed: true, correct_answer: answer, correct_choice_no: 2,
        explanation: '채점 결과', points: {status: 'granted', granted_points: 20, balance_after: 30}};
    } else if (endpoint.endsWith('/questions/1/')) {
      data = {total_questions: 10, attempt_count: 0, max_attempts: 3, is_finalized: false,
        question: {subject, question_type: kind, difficulty: 'beginner', question_text: '검증 문제',
          code_snippet: '', choices: [
            {choice_uuid: 'e4604483-225c-4a5b-8809-cad8341653d5', choice_no: 1, choice_text: 'wrong'},
            {choice_uuid: choiceId, choice_no: 2, choice_text: answer},
          ]}};
    } else if (endpoint.endsWith('/sessions/')) {
      data = {session_id: 42, total_questions: 10, points_summary: {wallet_balance: 10}};
    } else {
      throw new Error(`Unexpected request: ${endpoint}`);
    }
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(data)});
  });
  try {
    await page.goto('http://campus.test/');
    await page.evaluate(({subject, kind}) => window.CampusLearning.open(kind, subject), {subject, kind});
    await page.waitForFunction(() => document.getElementById('learning-app').getAttribute('aria-busy') === 'false');
    assert.equal(requests.filter(item => item.endpoint.endsWith('/content-open/')).length, 1);
    assert.match(await page.locator('#learning-wallet').textContent(), /10P/);
    await page.locator('[data-difficulty="beginner"]').click();
    await page.waitForFunction(() => document.getElementById('question-title').textContent === '검증 문제');
    if (kind === 'multiple_choice') await page.locator('#choice-list input').nth(1).check();
    else await page.locator('#blank-answer').fill(answer);
    await page.locator('#submit-button').click();
    await page.waitForFunction(() => !document.getElementById('error-message').hidden);
    await page.waitForFunction(() => document.getElementById('learning-app').getAttribute('aria-busy') === 'false');
    await page.locator('#submit-button').click();
    await page.waitForFunction(() => !document.getElementById('feedback').hidden);
    await page.waitForFunction(() => document.getElementById('learning-app').getAttribute('aria-busy') === 'false');
    assert.equal(await page.locator('#feedback-points').textContent(), '+20P 적립 완료');
    assert.match(await page.locator('#learning-wallet').textContent(), /30P/);
    assert.equal(requests.filter(item => item.endpoint.endsWith('/content-open/')).length, 1,
      'Difficulty selection and answer retries must not create another panel-open event');
    assert.deepEqual(errors, []);
    if (process.env.CAMPUS_UI_ARTIFACT_DIR) {
      fs.mkdirSync(process.env.CAMPUS_UI_ARTIFACT_DIR, {recursive: true});
      await page.screenshot({path: path.join(process.env.CAMPUS_UI_ARTIFACT_DIR, `${subject}-${kind}.png`)});
    }
    console.log(`PASS ${subject} ${kind}: open, selected choice, stable retry, grant and balance`);
  } finally {
    await context.close();
  }
}

(async () => {
  const browser = await chromium.launch({channel: 'chrome', headless: true});
  try {
    for (const subject of ['python', 'sql']) {
      for (const kind of ['multiple_choice', 'fill_blank']) await scenario(browser, subject, kind);
    }
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
