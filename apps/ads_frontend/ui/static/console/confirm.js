// 되돌릴 수 없는 동작의 확인 창(설계 D3-1: JS 가 없으면 확인 없이 바로 제출된다 — 서버는 같은 규칙을 그대로 지킨다).
// 폼 전체(`form[data-confirm]`) 또는 누른 버튼(`button[data-confirm]` — 한 폼에 버튼이 여럿일 때 그 버튼만)에 붙인다.
// 광고주 화면(body.console)은 시안의 자체 창(<dialog>): data-confirm 은 제목, -detail 은 설명, -action 은 실행 버튼 이름, -summary 는 함께 보일 <dl> 의 id.
// 운영 화면(Django admin 모양)은 브라우저 기본 창(window.confirm)을 그대로 쓴다.
(() => {
  const confirmed = new WeakSet();  // 확인을 마치고 다시 보내는 제출은 묻지 않는다

  const dialogFor = (source, submitter) => {
    const dialog = document.createElement("dialog");
    dialog.className = "confirm";
    const el = (tag, className, text) => { const e = document.createElement(tag); if (className) e.className = className; if (text) e.textContent = text; return e; };
    const danger = submitter && submitter.classList.contains("danger");
    dialog.append(el("span", `glyph${danger ? " danger" : ""}`, "!"), el("h2", "", source.getAttribute("data-confirm")));
    if (source.dataset.confirmDetail) dialog.append(el("p", "muted", source.dataset.confirmDetail));
    const summary = source.dataset.confirmSummary && document.getElementById(source.dataset.confirmSummary);
    if (summary) { const copy = summary.cloneNode(true); copy.removeAttribute("id"); copy.hidden = false; copy.className = "summary"; dialog.append(copy); }
    const form = el("form", "actions");
    form.method = "dialog";
    const cancel = el("button", "secondary", "돌아가기"); cancel.value = "cancel";
    const ok = el("button", danger ? "danger" : "", source.dataset.confirmAction || (submitter && submitter.textContent.trim()) || "확인"); ok.value = "ok";
    form.append(cancel, ok);
    dialog.append(form);
    return dialog;
  };

  document.addEventListener("submit", (event) => {
    const form = event.target, submitter = event.submitter;
    const source = submitter && submitter.hasAttribute("data-confirm") ? submitter : form.hasAttribute("data-confirm") ? form : null;
    if (!source) return;
    if (confirmed.has(form)) { confirmed.delete(form); return; }
    if (!document.body.classList.contains("console") || typeof HTMLDialogElement !== "function") {
      if (!window.confirm(source.getAttribute("data-confirm"))) event.preventDefault();
      return;
    }
    event.preventDefault();
    const dialog = dialogFor(source, submitter);
    dialog.addEventListener("close", () => {
      dialog.remove();
      if (dialog.returnValue !== "ok") return;
      confirmed.add(form);
      form.requestSubmit(submitter && submitter.form === form ? submitter : undefined);
    });
    document.body.append(dialog);
    dialog.showModal();  // 첫 버튼(돌아가기)에 초점 — Esc 는 취소
  });
})();
