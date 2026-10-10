// 되돌릴 수 없는 동작의 확인 창(설계 D3-1: JS 가 없으면 확인 없이 바로 제출된다 — 서버는 같은 규칙을 그대로 지킨다).
document.addEventListener("submit", (event) => {
  const message = event.target.getAttribute("data-confirm");
  if (message && !window.confirm(message)) event.preventDefault();
});
