// 고르면 바로 다시 본다(JS 가 있을 때만 — 없으면 옆의 '보기' 버튼으로 제출한다, 설계 D3-1). `form.autosubmit` 안의 선택 상자에만.
// `data-swap="<id>"` 가 붙은 폼은 페이지 전체 대신 그 id 의 부분만 바꾼다: 같은 주소를 받아 그 요소만 갈아 끼우고 주소창도 맞춘다.
// 서버는 그대로(같은 화면을 그린다), 받기에 실패하면 그냥 제출한다.
document.documentElement.classList.add("js");
document.addEventListener("change", async (event) => {
  const field = event.target;
  if (!field.matches("form.autosubmit select")) return;
  const form = field.form;
  const part = form.dataset.swap && document.getElementById(form.dataset.swap);
  if (!part) return form.requestSubmit();
  const url = new URL(location.href);
  url.search = new URLSearchParams(new FormData(form)).toString();  // GET 제출과 같은 주소
  try {
    const response = await fetch(url, { headers: { Accept: "text/html" } });
    const fresh = response.ok && new DOMParser().parseFromString(await response.text(), "text/html").getElementById(part.id);
    if (!fresh) throw new Error(`부분을 받지 못함(${response.status})`);
    part.replaceWith(fresh);
    history.replaceState(null, "", url);
    // 다른 폼(기간 고르기)이 숨겨 들고 있는 같은 값도 맞춘다 — 기간을 바꿀 때 고른 지표가 이어진다
    document.querySelectorAll(`input[type="hidden"][name="${field.name}"]`).forEach((input) => { input.value = field.value; });
    fresh.querySelector(`select[name="${field.name}"]`)?.focus();  // 갈아 끼운 뒤에도 키보드 위치를 잃지 않게
  } catch {
    form.requestSubmit();
  }
});
