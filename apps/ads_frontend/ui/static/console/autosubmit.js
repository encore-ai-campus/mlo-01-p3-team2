// 고르면 바로 다시 본다(JS 가 있을 때만 — 없으면 옆의 '보기' 버튼으로 제출한다, 설계 D3-1). `form.autosubmit` 안의 선택 상자에만.
document.documentElement.classList.add("js");
document.addEventListener("change", (event) => {
  const field = event.target;
  if (field.matches("form.autosubmit select")) field.form.requestSubmit();
});
