/* First-visit instructions use example captures and a per-account completion flag. */
(() => {
  'use strict';
  const get = id => document.getElementById(id);
  const dialog = get('campusGuideDialog'), zoom = get('campusGuideImageDialog');
  if (!dialog || !zoom) return;
  const config = JSON.parse(get('campusViewConfig')?.textContent || '{}');
  const steps = [
    {
      category: '이동과 상호작용', title: '캠퍼스에 오신 것을 환영해요', image: 'campus.jpg',
      alt: '18층 캠퍼스 지도와 화면 아래의 이동 및 상호작용 조작 안내 예시',
      text: '캐릭터로 캠퍼스를 둘러보고, 사람들과 이야기하거나 학습과 게임을 즐길 수 있어요.',
      items: ['WASD 또는 방향키로 이동해요. 스페이스바로 점프하고, 이동하면서도 뛸 수 있어요.', '시설 가까이에서 E를 눌러 안내를 보거나 상호작용해요.', '가까운 캐릭터를 향해 Z를 누르면 찌르기, 길게 누르면 연속 찌르기가 돼요.'],
      keys: ['WASD 이동', 'Space 점프', 'E 상호작용', 'Z 찌르기'],
    },
    {
      category: '층 이동', title: '18층과 옥상을 오가요', image: 'floor-movement.jpg',
      alt: '상담실 B 옆에 있는 18층 옥상 연결 계단의 실제 화면 예시',
      text: '18층 캠퍼스와 옥상 광장은 계단으로 연결돼 있어요. 층이 바뀔 때는 잠시 로딩 화면이 표시돼요.',
      items: ['18층 오른쪽 상담실 B 옆 계단을 찾아가세요. 라운지 쪽 옆문으로 들어가 계단 위로 걸어가거나, 가까이에서 E를 누르면 옥상으로 올라가요.', '18층으로 돌아올 때는 옥상 입구 계단 아래쪽으로 걸어가거나, 계단 가까이에서 E를 누르세요.', '빠른 이동: 18층 라운지 2 소화기 근처에서 E를 누르고 예를 선택하면 옥상 왼편 포탈로 이동해요. 옥상 왼편 포탈에서도 18층으로 돌아올 수 있어요.'],
      keys: ['계단으로 걸어 이동', '계단 근처에서 E', '빠른 이동은 예 선택'],
    },
    {
      category: '채팅과 게시판', title: '인사하고 소식을 나눠요', image: 'community.jpg',
      alt: '18층 게시판에서 구내식당 메뉴와 엔코아 타임 카드를 고르는 화면 예시',
      text: '같이 접속한 사람들과 채팅하고, 게시판에서 식단과 커뮤니티 글을 확인해 보세요.',
      items: ['Enter를 눌러 채팅을 입력하고 전송해요. Esc로 입력을 끝내고 이동할 수 있어요.', '18층 화면의 게시판 열기를 누르거나 게시판 가까이에서 E를 눌러요.', '구내식당 메뉴에서 식단을, 엔코아 타임에서 글과 댓글을 확인할 수 있어요.'],
      keys: ['Enter 채팅', 'Esc 입력 종료'],
    },
    {
      category: '학습교실', title: '박스 안에서 E를 눌러요', image: 'classroom.jpg',
      alt: 'Python 학습교실의 객관식 및 코드 빈칸 학습 영역과 중앙 하단 조작 안내 예시',
      text: 'Python 또는 SQL 학습교실에 들어가면 객관식과 코드 빈칸 문제를 풀 수 있어요.',
      items: ['18층에서 Python 또는 SQL 학습교실 출입구로 들어가요.', '원하는 학습 유형의 표시된 박스 안으로 이동한 뒤 E를 눌러요.', '나갈 때는 교실 출입구로 이동해 하단에 메타버스로 나가기 안내가 나오면 E를 눌러요.'],
      keys: ['박스 안에서 E 상호작용'],
    },
    {
      category: '문제 풀이', title: '나에게 맞는 난이도로 시작해요', image: 'quiz.jpg',
      alt: '초급 코드 빈칸 문제에서 구체적인 요구 동작을 읽고 답을 제출하는 화면 예시',
      text: '초급·중급·고급 중 하나를 고르면 한 번에 10문제를 학습해요.',
      items: ['객관식은 보기를 고르고, 코드 빈칸은 답만 입력한 뒤 제출하기를 눌러요. 버튼이 안 보이면 문제창 안을 아래로 스크롤하세요.', '한 문제에 최대 세 번 도전할 수 있어요. Python 답안은 대소문자도 확인해 주세요.', '학습을 마치면 결과와 적립 포인트를 확인하고 틀린 문제를 다시 볼 수 있어요.'],
      keys: ['초급 · 중급 · 고급', '문제당 최대 3회'],
    },
    {
      category: '포인트', title: '정답을 맞히면 포인트가 쌓여요', image: 'points.jpg',
      alt: '지도 확대 축소 버튼 아래의 보유 포인트와 펼쳐진 적립 내역 예시',
      text: '보유 포인트는 지도 확대·축소 버튼 아래의 코인 옆에 표시돼요.',
      items: ['기본 적립은 정답 한 문제당 초급 20P, 중급 50P, 고급 80P예요.', '보유 포인트를 누르면 과목·난이도·적립 시각 등 최근 적립 내역이 펼쳐져요.', '더 보기가 표시되면 이전 내역도 확인할 수 있어요. 실제 적립액은 제출 결과를 확인해 주세요.'],
      keys: ['보유 포인트 클릭 → 적립 내역'],
    },
    {
      category: '옥상 부스', title: '잠깐 쉬어가는 시간도 가져요', image: 'rooftop.jpg',
      alt: '옥상 광장에 나란히 배치된 유튜브 스튜디오와 심리 테스트 및 게임 부스 예시',
      text: '18층 연결 계단을 이용하면 옥상 광장으로 이동할 수 있어요.',
      items: ['유튜브 스튜디오, 심리 테스트 존, 게임 부스 중앙에서 E를 눌러 콘텐츠를 열어요.', '게임 부스에서는 오목, 테트리스, 죽림고수, 솔리테어 등 16가지 게임을 고를 수 있어요.', '콘텐츠는 별도 창이나 팝업으로 열릴 수 있어요. 열리지 않으면 브라우저의 팝업 차단을 확인해 주세요.'],
      keys: ['부스 중앙에서 E', '게임 16종'],
    },
    {
      category: '설정과 다시 보기', title: '이제 캠퍼스를 둘러볼까요', image: 'settings.jpg',
      alt: '설정 창의 닉네임 및 채팅창 표시 선택과 처음 이용 안내 다시 보기 버튼 예시',
      text: '하단 오른쪽의 나의 캐릭터·닉네임 옆 설정 버튼을 누르거나 Esc를 눌러 설정을 열어요. 이 안내는 회원가입 후 첫 접속 때 보여요.',
      items: ['다른 사람 닉네임, 채팅창, 말풍선 표시를 각각 켜고 끌 수 있어요.', '내 계정에서 닉네임을 변경하거나 로그아웃할 수 있어요.', '사용하다 헷갈리면 설정 → 처음 이용 안내 다시 보기를 눌러 주세요.'],
      keys: ['하단 오른쪽 설정 · Esc', '설정 → 처음 이용 안내 다시 보기'],
    },
  ];
  let index = 0, returnFocus = null, saving = false, pending = config.guidePending === true;
  const dots = get('campusGuideSteps');
  steps.forEach((step, number) => {
    const button = document.createElement('button');
    button.type = 'button'; button.className = 'campus-guide-dot';
    button.setAttribute('aria-label', `${number + 1}단계 ${step.category}`);
    button.addEventListener('click', () => show(number));
    dots.append(button);
  });
  function source(step) { return new URL(`assets/guide/${step.image}?v=20261015-window-layout`, document.baseURI).href; }
  function show(number) {
    index = Math.max(0, Math.min(number, steps.length - 1));
    const step = steps[index], image = get('campusGuideImage');
    get('campusGuideCategory').textContent = step.category;
    get('campusGuideTitle').textContent = step.title;
    get('campusGuideText').textContent = step.text;
    get('campusGuideCounter').textContent = `${index + 1} / ${steps.length}`;
    get('campusGuideItems').replaceChildren(...step.items.map(text => { const item = document.createElement('li'); item.textContent = text; return item; }));
    get('campusGuideKeys').replaceChildren(...step.keys.map(text => { const item = document.createElement('span'); item.textContent = text; return item; }));
    image.alt = step.alt; image.src = source(step); image.hidden = false;
    get('campusGuideImageError').hidden = true;
    get('campusGuideEnlarge').disabled = false;
    get('campusGuideBack').disabled = index === 0;
    get('campusGuideNext').textContent = index === steps.length - 1 ? '캠퍼스 시작하기' : '다음';
    [...dots.children].forEach((button, number) => {
      if (number === index) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
    });
    get('campusGuideScroll').scrollTop = 0;
    if (dialog.open) get('campusGuideTitle').focus({preventScroll: true});
  }
  function open() {
    if (dialog.open || window.CampusSession?.ending) return;
    pending = false;
    returnFocus = document.activeElement;
    const settings = get('settingsDialog'); if (settings?.open) settings.close();
    show(0);
    window.dispatchEvent(new Event('campus:guide-open'));
    dialog.showModal(); get('campusGuideTitle').focus({preventScroll: true});
  }
  async function finish() {
    if (zoom.open) zoom.close();
    dialog.close();
    const target = returnFocus?.isConnected && !returnFocus.closest('dialog:not([open])') ? returnFocus : get('mapCanvas');
    target?.focus({preventScroll: true});
    window.dispatchEvent(new Event('campus:guide-close'));
    if (saving || !config.guideCompleteUrl) return;
    saving = true;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 10000);
    try {
      const policy = JSON.parse(get('campusSessionPolicyConfig')?.textContent || '{}');
      const response = await fetch(config.guideCompleteUrl, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        headers: {'X-CSRFToken': policy.csrfToken || ''}, signal: controller.signal});
      if (!response.ok || response.redirected || (await response.json()).guideCompleted !== true) throw new Error('Guide completion unavailable');
      config.guidePending = false;
    } catch {
      window.CampusApp?.toast('안내 확인 상태를 저장하지 못했어요. 다음 접속 때 다시 표시될 수 있어요.');
    } finally { clearTimeout(timer); saving = false; }
  }
  get('campusGuideImage').addEventListener('error', () => {
    get('campusGuideImage').hidden = true; get('campusGuideImageError').hidden = false;
    get('campusGuideEnlarge').disabled = true;
  });
  get('campusGuideOpen').addEventListener('click', open);
  get('campusGuideBack').addEventListener('click', () => show(index - 1));
  get('campusGuideNext').addEventListener('click', () => index === steps.length - 1 ? finish() : show(index + 1));
  get('campusGuideSkip').addEventListener('click', finish);
  dialog.addEventListener('cancel', event => { event.preventDefault(); finish(); });
  dialog.addEventListener('keydown', event => {
    event.stopPropagation();
    if (event.altKey || event.ctrlKey || event.metaKey || event.isComposing) return;
    if (event.key === 'ArrowRight') { event.preventDefault(); if (index < steps.length - 1) show(index + 1); }
    if (event.key === 'ArrowLeft') { event.preventDefault(); show(index - 1); }
  });
  get('campusGuideEnlarge').addEventListener('click', () => {
    const image = get('campusGuideLargeImage'); image.src = source(steps[index]); image.alt = steps[index].alt;
    get('campusGuideLargeTitle').textContent = steps[index].category + ' 화면 예시';
    zoom.showModal(); get('campusGuideImageClose').focus({preventScroll: true});
  });
  get('campusGuideImageClose').addEventListener('click', () => zoom.close());
  zoom.addEventListener('keydown', event => event.stopPropagation());
  zoom.addEventListener('close', () => { if (dialog.open) get('campusGuideEnlarge').focus({preventScroll: true}); });
  window.addEventListener('campus:ready', () => {
    if (config.guidePending === true) requestAnimationFrame(() => open());
  }, {once: true});
  window.CampusGuide = {open, get pending() { return pending; }, get blocking() { return dialog.open || zoom.open; }};
})();
