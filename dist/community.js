(() => {
  'use strict';
  function create({onBack}) {
    const $ = id => document.getElementById(id), panel = $('communityPanel'), dialog = $('boardDialog');
    const main = $('communityContent'), editor = $('communityEditor'), commentForm = $('communityCommentForm');
    const originalTitle = $('boardTitle').textContent, originalEyebrow = $('boardEyebrow').textContent;
    let active = false, busy = false, mode = 'list', category = 'all', search = '', page = 1;
    let meta = null, post = null, editingPost = null, editingComment = null, replyingTo = null, editorBaseline = '';
    let commentPage = 1, generation = 0, controller = null;
    const node = (tag, className, text) => {
      const item = document.createElement(tag);
      if (className) item.className = className;
      if (text !== undefined) item.textContent = text;
      return item;
    };
    function button(text, handler, className = 'toolbtn') {
      const item = node('button', className, text); item.type = 'button';
      item.addEventListener('click', () => { if (!busy) handler(); }); return item;
    }
    function status(message = '', failure = false) {
      const target = $('communityStatus'); target.textContent = message; target.hidden = !message;
      target.dataset.error = String(failure); target.setAttribute('role', failure ? 'alert' : 'status');
    }
    function report(error) {
      if (error.name === 'AbortError' || !active) return;
      status(error.message || '요청을 처리하지 못했어요. 다시 시도해 주세요.', true);
      for (const [field, id] of [['title', 'communityTitleError'], ['body', 'communityBodyError']]) {
        const messages = error.fields?.[field];
        $(id).textContent = messages?.join(' ') || ''; $(id).hidden = !messages;
      }
      main.scrollTop = 0;
    }
    async function api(path, {method = 'GET', body, signal} = {}) {
      const headers = {Accept: 'application/json'};
      if (method !== 'GET') {
        const token = document.querySelector('#campusLogoutForm input[name="csrfmiddlewaretoken"]')?.value;
        if (!token) throw new Error('로그인한 캠퍼스에서 이용해 주세요.');
        headers['X-CSRFToken'] = token;
        if (body !== undefined) headers['Content-Type'] = 'application/json';
      }
      const response = await fetch('/api/community/' + path, {method, credentials: 'same-origin', cache: 'no-store', headers, signal,
        ...(body === undefined ? {} : {body: JSON.stringify(body)})});
      if (response.redirected || response.status === 401) throw new Error('로그인이 만료됐어요. 다시 로그인해 주세요.');
      if (!response.headers.get('content-type')?.includes('application/json')) {
        throw new Error(response.status === 403 ? '로그인 상태를 확인하고 새로고침해 주세요.' : '커뮤니티에 연결하지 못했어요. 다시 시도해 주세요.');
      }
      const data = await response.json();
      if (!response.ok) { const error = new Error(data.error || '요청을 처리하지 못했어요.'); error.fields = data.fields; error.status = response.status; throw error; }
      return data;
    }
    function beginLoad() {
      controller?.abort(); controller = new AbortController(); generation++;
      main.setAttribute('aria-busy', 'true'); status('불러오는 중이에요.');
      return {signal: controller.signal, version: generation};
    }
    function current(load) { return active && generation === load.version; }
    function finishLoad(load) { if (current(load)) main.setAttribute('aria-busy', String(busy)); }
    function editorSignature() { return JSON.stringify([$('communityCategory').value, $('communityTitle').value, $('communityBody').value]); }
    function dirty() {
      if (!active) return false;
      if (mode === 'editor') return editorSignature() !== editorBaseline;
      return mode === 'detail' && $('communityCommentBody').value !== (editingComment?.body || '');
    }
    function canLeave() {
      if (busy) { status('저장 중이에요. 잠시만 기다려 주세요.'); return false; }
      return !dirty() || window.confirm('작성 중인 내용이 있어요. 저장하지 않고 나갈까요?');
    }
    function setMode(next) {
      mode = next;
      $('communityListView').hidden = next !== 'list'; $('communityPostView').hidden = next !== 'detail'; editor.hidden = next !== 'editor';
      $('communityWrite').hidden = next !== 'list' || !canWriteCategory();
      updateHeading();
    }
    function currentCategory() { return meta?.categories.find(item => item.id === category); }
    function canWriteCategory() { return category === 'all' || currentCategory()?.canWrite === true; }
    function updateHeading() {
      const item = currentCategory();
      $('communityHeading').textContent = mode === 'editor' ? (editingPost ? '글 수정' : '글쓰기') : mode === 'detail' ? '게시글' : item?.name || '전체글';
      $('communityDescription').textContent = mode === 'editor' ? '정보와 경험을 나누고 함께 성장해요.' : mode === 'detail' ? '댓글로 질문과 피드백을 나눠 보세요.' : item?.description || '캠퍼스의 모든 이야기를 한곳에서 만나보세요.';
    }
    function renderMeta(value) {
      meta = value;
      $('communityNickname').textContent = meta.user.nickname; $('communityRole').textContent = meta.user.isAdmin ? '관리자' : '멤버';
      const nav = $('communityTabs'); nav.replaceChildren();
      nav.setAttribute('aria-orientation', window.matchMedia('(max-width:680px)').matches ? 'horizontal' : 'vertical');
      const tabs = [{id: 'all', name: '전체글', count: meta.total}, ...meta.categories];
      for (const item of tabs) {
        const tab = button('', () => selectCategory(item.id), 'community-tab');
        tab.id = 'communityTab-' + item.id; tab.dataset.category = item.id;
        tab.setAttribute('role', 'tab'); tab.setAttribute('aria-controls', 'communityContent');
        tab.setAttribute('aria-selected', String(category === item.id)); tab.tabIndex = category === item.id ? 0 : -1;
        const dot = node('span', 'community-tab-dot'); dot.setAttribute('aria-hidden', 'true');
        tab.append(dot, node('span', 'community-tab-label', item.name), node('span', 'community-tab-count', String(item.count)));
        tab.addEventListener('keydown', event => {
          if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const index = tabs.findIndex(other => other.id === item.id);
          const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (['ArrowDown', 'ArrowRight'].includes(event.key) ? 1 : tabs.length - 1)) % tabs.length;
          if (canLeave()) { selectCategory(tabs[next].id, true); }
        });
        nav.append(tab);
      }
      main.setAttribute('aria-labelledby', 'communityTab-' + category);
      updateHeading(); $('communityWrite').hidden = mode !== 'list' || !canWriteCategory();
    }
    async function refreshMeta() {
      try { const value = await api(''); if (!active) return false; renderMeta(value); return true; }
      catch (error) { report(error); return false; }
    }
    function selectCategory(id, approved = false) {
      if ((!approved && !canLeave()) || busy) return;
      category = id; search = ''; page = 1; $('communitySearchInput').value = '';
      loadList({focus: true});
    }
    const fullDate = value => new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false}).format(new Date(value));
    const shortDate = value => new Intl.DateTimeFormat('ko-KR', {timeZone: 'Asia/Seoul', month: '2-digit', day: '2-digit'}).format(new Date(value));
    function categoryBadge(item) {
      const badge = node('span', 'community-category', item.categoryLabel); badge.dataset.category = item.category; return badge;
    }
    function renderPagination(target, pagination, action) {
      target.replaceChildren(); target.hidden = pagination.pages <= 1;
      const previous = button('‹ 이전', () => action(pagination.page - 1), ''); previous.disabled = pagination.page <= 1; target.append(previous);
      const start = Math.max(1, Math.min(pagination.page - 2, pagination.pages - 4));
      for (let number = start; number <= Math.min(pagination.pages, start + 4); number++) {
        const item = button(String(number), () => action(number), ''); item.setAttribute('aria-label', number + '페이지');
        if (number === pagination.page) item.setAttribute('aria-current', 'page'); target.append(item);
      }
      const next = button('다음 ›', () => action(pagination.page + 1), ''); next.disabled = pagination.page >= pagination.pages; target.append(next);
    }
    function emptyRow(message, explanation, retry = false) {
      const row = node('tr'), cell = node('td'), empty = node('div', 'community-empty'); cell.colSpan = 5;
      const mark = node('span', 'community-empty-mark', '≡'); mark.setAttribute('aria-hidden', 'true');
      empty.append(mark, node('h4', '', message), node('p', '', explanation));
      if (retry) empty.append(button('다시 불러오기', () => loadList(), 'btn quiet'));
      else if (canWriteCategory() && !search) empty.append(button('첫 글 쓰기', () => compose(), 'btn quiet'));
      cell.append(empty); row.append(cell); return row;
    }
    function renderPosts(data) {
      page = data.pagination.page;
      $('communityPostCount').textContent = (search ? '검색 결과 ' : '전체 ') + data.pagination.total.toLocaleString('ko-KR') + '개';
      $('communitySearchReset').hidden = !search;
      const rows = $('communityPostRows'); rows.replaceChildren();
      for (const item of data.posts) {
        const row = node('tr'); row.dataset.postId = String(item.id);
        const subject = node('td', 'community-subject'), link = button('', () => openPost(item.id), 'community-subject-button');
        link.append(categoryBadge(item), node('span', 'community-subject-title', item.title)); link.setAttribute('aria-label', item.title + ' 읽기'); subject.append(link);
        const author = node('td', 'community-author', item.author.nickname); author.title = item.author.nickname;
        const date = node('td', 'community-date', shortDate(item.createdAt)); date.title = fullDate(item.createdAt);
        row.append(node('td', 'community-number', String(item.id)), subject, author, date, node('td', 'community-replies', String(item.commentCount))); rows.append(row);
      }
      if (!data.posts.length) rows.append(emptyRow(search ? '검색 결과가 없어요' : '아직 등록된 글이 없어요', search ? '다른 검색어로 다시 찾아보세요.' : canWriteCategory() ? '이 게시판의 첫 이야기를 남겨 보세요.' : '관리자가 공지사항을 등록하면 이곳에서 볼 수 있어요.'));
      renderPagination($('communityPagination'), data.pagination, next => {page = next; loadList({focus: true});});
    }
    async function loadList({focus = false} = {}) {
      const load = beginLoad(); post = editingPost = null;
      resetComment(); setMode('list');
      try {
        const params = new URLSearchParams({category, q: search, page: String(page)});
        const [value, data] = await Promise.all([api('', {signal: load.signal}), api('posts/?' + params, {signal: load.signal})]);
        if (!current(load)) return;
        renderMeta(value); renderPosts(data); status(); main.scrollTop = 0;
        if (focus) $('communityHeading').focus({preventScroll: true});
      } catch (error) {
        if (current(load) && error.name !== 'AbortError') { $('communityPostRows').replaceChildren(emptyRow('목록을 불러오지 못했어요', '잠시 후 다시 시도해 주세요.', true)); report(error); }
      } finally { finishLoad(load); }
    }
    function richText(target, text) {
      target.replaceChildren(); let offset = 0;
      for (const match of text.matchAll(/https?:\/\/[^\s<>"']+/g)) {
        const address = match[0].replace(/[.,!?;:)\]}]+$/g, '');
        target.append(document.createTextNode(text.slice(offset, match.index)));
        const link = node('a', '', address); link.href = address; link.target = '_blank'; link.rel = 'noopener noreferrer'; target.append(link);
        offset = match.index + address.length;
      }
      target.append(document.createTextNode(text.slice(offset)));
    }
    function resetComment() {
      editingComment = replyingTo = null; commentForm.reset(); $('communityCommentLabel').textContent = '댓글 남기기';
      $('communityCommentCancel').hidden = true; $('communityCommentCancel').textContent = '취소';
      $('communityCommentSubmit').textContent = '댓글 등록'; updateLengths();
    }
    function renderDetail(value, comments) {
      post = value; editingPost = null; setMode('detail'); resetComment();
      const badge = $('communityPostCategory'); badge.textContent = post.categoryLabel; badge.dataset.category = post.category;
      $('communityPostTitle').textContent = post.title;
      const details = $('communityPostMeta'); details.replaceChildren(node('strong', '', post.author.nickname), node('span', '', fullDate(post.createdAt)));
      details.append(node('span', '', '최근 저장 · ' + fullDate(post.updatedAt)));
      if (meta?.user.isAdmin && post.author.id !== meta.user.id) details.append(node('span', '', '관리자 권한으로 관리할 수 있어요.'));
      richText($('communityPostBody'), post.body); $('communityEdit').hidden = !post.canEdit; $('communityDelete').hidden = !post.canDelete;
      renderComments(comments); main.scrollTop = 0; $('communityPostTitle').focus({preventScroll: true});
    }
    async function openPost(id) {
      const load = beginLoad();
      try {
        const [data, comments] = await Promise.all([api(`posts/${id}/`, {signal: load.signal}), api(`posts/${id}/comments/`, {signal: load.signal})]);
        if (!current(load)) return; renderDetail(data.post, comments); status();
      } catch (error) { if (current(load)) report(error); }
      finally { finishLoad(load); }
    }
    function renderComment(item) {
      const row = node('li', 'community-comment' + (item.parentCommentUuid ? ' community-comment-reply' : ''));
      row.dataset.commentId = String(item.id); row.dataset.deleted = String(Boolean(item.isDeleted));
      if (!item.isDeleted) {
        const heading = node('div', 'community-comment-heading'); heading.append(node('strong', '', item.author.nickname), node('span', '', fullDate(item.createdAt)));
        const actions = node('div', 'community-comment-actions');
        if (item.canReply) actions.append(button('답글', () => {
          if (!canLeave()) return; resetComment(); replyingTo = {...item, page: commentPage};
          $('communityCommentLabel').textContent = item.author.nickname + '님에게 답글 남기기';
          $('communityCommentCancel').hidden = false; $('communityCommentCancel').textContent = '답글 취소';
          $('communityCommentSubmit').textContent = '답글 등록';
          $('communityCommentBody').focus(); commentForm.scrollIntoView({block: 'nearest'});
        }, ''));
        if (item.canEdit) actions.append(button('수정', () => {
          if (!canLeave()) return; resetComment(); editingComment = item; $('communityCommentBody').value = item.body;
          $('communityCommentLabel').textContent = item.parentCommentUuid ? '답글 수정' : '댓글 수정';
          $('communityCommentCancel').hidden = false; $('communityCommentCancel').textContent = '수정 취소'; $('communityCommentSubmit').textContent = '수정 저장';
          updateLengths(); $('communityCommentBody').focus(); commentForm.scrollIntoView({block: 'nearest'});
        }, ''));
        if (item.canDelete) actions.append(button('삭제', () => deleteComment(item), ''));
        heading.append(actions); row.append(heading);
      }
      const body = node('p', 'community-comment-body'); richText(body, item.body); row.append(body);
      if (item.replies?.length) {
        const replies = node('ul', 'community-comment-replies'); replies.setAttribute('aria-label', '답글');
        for (const reply of item.replies) replies.append(renderComment(reply));
        row.append(replies);
      }
      return row;
    }
    function renderComments(data) {
      commentPage = data.pagination.page; post.commentCount = data.commentCount ?? data.pagination.total;
      $('communityCommentCount').textContent = String(post.commentCount);
      const list = $('communityComments'); list.replaceChildren();
      for (const item of data.comments) list.append(renderComment(item));
      if (!data.comments.length) list.append(node('li', 'community-comment-empty', '아직 댓글이 없어요. 첫 피드백을 남겨 주세요.'));
      renderPagination($('communityCommentPages'), data.pagination, next => {if (canLeave()) {resetComment(); loadComments(next);}});
    }
    async function loadComments(next = commentPage) {
      if (!post || mode !== 'detail') return;
      const id = post.id, load = beginLoad();
      try {
        const data = await api(`posts/${id}/comments/?page=${next}`, {signal: load.signal});
        if (!current(load) || post?.id !== id || mode !== 'detail') return false; renderComments(data); status(); return true;
      } catch (error) { if (current(load)) report(error); return false; }
      finally { finishLoad(load); }
    }
    function compose(item = null) {
      if (!meta || !canLeave() || (!item && !canWriteCategory())) return;
      controller?.abort(); generation++; status(); editingPost = item;
      const options = $('communityCategory'); options.replaceChildren();
      for (const tab of meta.categories.filter(tab => tab.canWrite)) { const option = node('option', '', tab.name); option.value = tab.id; options.append(option); }
      options.value = item?.category || (category !== 'all' && currentCategory()?.canWrite ? category : 'free');
      $('communityTitle').value = item?.title || ''; $('communityBody').value = item?.body || '';
      for (const id of ['communityTitleError', 'communityBodyError']) {$(id).hidden = true; $(id).textContent = '';}
      $('communityEditorSubmit').textContent = item ? '수정 저장' : '등록하기'; setMode('editor'); editorBaseline = editorSignature();
      updateLengths(); main.scrollTop = 0; $('communityTitle').focus({preventScroll: true}); main.setAttribute('aria-busy', 'false');
    }
    function updateLengths() {
      $('communityTitleLength').textContent = $('communityTitle').value.length + ' / 140';
      $('communityBodyLength').textContent = $('communityBody').value.length.toLocaleString('ko-KR') + ' / 20,000';
      $('communityCommentLength').textContent = $('communityCommentBody').value.length.toLocaleString('ko-KR') + ' / 2,000';
    }
    async function mutate(action) {
      if (busy) return;
      busy = true; main.setAttribute('aria-busy', 'true'); status('저장 중이에요.');
      const disabled = new Map([...panel.querySelectorAll('button,input,textarea,select')].map(item => [item, item.disabled]));
      for (const item of disabled.keys()) item.disabled = true;
      try { await action(); } catch (error) { report(error); }
      finally { busy = false; for (const [item, value] of disabled) item.disabled = value; main.setAttribute('aria-busy', 'false'); $('communityWrite').hidden = mode !== 'list' || !canWriteCategory(); }
    }
    async function savePost(event) {
      event.preventDefault(); if (busy) return;
      const data = {category: $('communityCategory').value, title: $('communityTitle').value, body: $('communityBody').value};
      const old = editingPost;
      if (!data.title.trim() || !data.body.trim()) { status('제목과 내용을 입력해 주세요.', true); return; }
      if (old) data.version = old.updatedAt;
      await mutate(async () => {
        const result = await api(old ? `posts/${old.id}/` : 'posts/', {method: old ? 'PATCH' : 'POST', body: data});
        editorBaseline = editorSignature();
        renderDetail(result.post, {comments: [], pagination: {page: 1, pages: 1, total: result.post.commentCount}});
        const [commentsLoaded, metaLoaded] = await Promise.all([loadComments(1), refreshMeta()]);
        if (commentsLoaded && metaLoaded) status(old ? '글을 수정했어요.' : '글을 등록했어요.');
      });
    }
    async function deletePost() {
      if (!post || busy || !canLeave() || !window.confirm('이 글을 삭제할까요? 댓글도 함께 삭제됩니다.')) return;
      const id = post.id;
      await mutate(async () => {await api(`posts/${id}/`, {method: 'DELETE'}); await loadList({focus: true}); status('글을 삭제했어요.');});
    }
    async function saveComment(event) {
      event.preventDefault(); if (busy || !post) return;
      const body = $('communityCommentBody').value, old = editingComment, reply = replyingTo, id = post.id;
      if (!body.trim()) {status('댓글을 입력해 주세요.', true); return;}
      await mutate(async () => {
        await api(old ? `comments/${old.id}/` : `posts/${id}/comments/`, {method: old ? 'PATCH' : 'POST',
          body: {body, ...(old ? {version: old.updatedAt} : reply ? {parentCommentUuid: reply.commentUuid} : {})}});
        const isReply = Boolean(reply || old?.parentCommentUuid);
        resetComment();
        if (await loadComments(old ? commentPage : reply ? reply.page : 100000)) {
          status(isReply ? (old ? '답글을 수정했어요.' : '답글을 등록했어요.') : (old ? '댓글을 수정했어요.' : '댓글을 등록했어요.'));
        }
      });
    }
    async function deleteComment(item) {
      if (busy || ((editingComment?.id === item.id || replyingTo?.id === item.id) && !canLeave()) ||
          !window.confirm(item.replies?.length ? '이 댓글을 삭제할까요? 답글은 그대로 남습니다.' : '이 댓글을 삭제할까요?')) return;
      await mutate(async () => {
        await api(`comments/${item.id}/`, {method: 'DELETE'});
        if (editingComment?.id === item.id || replyingTo?.id === item.id) resetComment();
        if (await loadComments()) status('댓글을 삭제했어요.');
      });
    }
    function hide() {
      active = false; controller?.abort(); generation++; panel.hidden = true; delete dialog.dataset.view;
      $('boardTitle').textContent = originalTitle; $('boardEyebrow').textContent = originalEyebrow;
      post = editingPost = null; editor.reset(); resetComment();
    }
    function open() {
      active = true; category = 'all'; search = ''; page = 1; $('communitySearchInput').value = '';
      $('boardChoices').hidden = $('boardDescription').hidden = $('boardSelection').hidden = true;
      $('boardMenuView').hidden = true; panel.hidden = false; dialog.dataset.view = 'community';
      $('boardTitle').textContent = '엔코아 타임'; $('boardEyebrow').textContent = 'CAMPUS COMMUNITY';
      loadList({focus: true});
    }
    $('communityBack').addEventListener('click', () => { if (canLeave()) onBack(); });
    $('communityWrite').addEventListener('click', () => { if (!busy) compose(); });
    $('communitySearch').addEventListener('submit', event => {event.preventDefault(); if (busy) return; search = $('communitySearchInput').value.trim(); page = 1; loadList({focus: true});});
    $('communitySearchReset').addEventListener('click', () => {if (busy) return; search = ''; page = 1; $('communitySearchInput').value = ''; loadList({focus: true});});
    $('communityListBack').addEventListener('click', () => {if (canLeave()) loadList({focus: true});});
    $('communityEdit').addEventListener('click', () => {if (!busy && post?.canEdit) compose(post);});
    $('communityDelete').addEventListener('click', deletePost);
    editor.addEventListener('submit', savePost);
    $('communityEditorCancel').addEventListener('click', () => {if (!canLeave()) return; if (editingPost) openPost(editingPost.id); else loadList({focus: true});});
    commentForm.addEventListener('submit', saveComment);
    $('communityCommentCancel').addEventListener('click', () => {if (canLeave()) resetComment();});
    $('communityCommentsRefresh').addEventListener('click', () => {if (!busy) loadComments();});
    for (const id of ['communityTitle', 'communityBody', 'communityCommentBody']) $(id).addEventListener('input', updateLengths);
    window.addEventListener('beforeunload', event => {if (dirty()) {event.preventDefault(); event.returnValue = '';}});
    return {open, hide, canLeave};
  }
  window.CampusCommunity = {create};
})();
