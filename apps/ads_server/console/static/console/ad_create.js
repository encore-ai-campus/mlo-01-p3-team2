// 광고 만들기의 편의 기능(설계 D3-1). 없어도 모든 흐름이 동작하고, 규칙은 여기 없다 — 서버(create_ad)가 다시 검증한다.
(() => {
  const form = document.querySelector("form.ad-create");
  if (!form) return;

  // 1) 과금 단위: 고른 단위의 게재 위치만 고를 수 있게 바로 거른다(JS 가 없으면 '이 단위의 게재 위치 보기' 버튼이 서버에서 다시 그린다).
  const slots = form.querySelectorAll('input[name="slot_ids"]');
  const hint = form.querySelector(".unit-hint");
  const apply = (unit) => {
    slots.forEach((box) => {
      const other = box.dataset.unit !== unit;
      box.disabled = other;
      if (other) box.checked = false;
    });
    if (hint) hint.hidden = true;
  };
  form.querySelectorAll('input[name="pricing_unit"]').forEach((radio) => radio.addEventListener("change", () => apply(radio.value)));
  form.querySelectorAll(".js-hide").forEach((element) => { element.hidden = true; });

  // 2) 글자 수(이름·제목 등 최대 길이가 있는 칸)
  form.querySelectorAll("input[maxlength]").forEach((input) => {
    const counter = document.createElement("span");
    counter.className = "muted counter";
    const update = () => { counter.textContent = `${input.value.length}/${input.maxLength}`; };
    input.after(counter);
    input.addEventListener("input", update);
    update();
  });

  // 3) 올리기 전 이미지 미리보기와 용량 안내(막지는 않는다)
  const file = form.querySelector('input[type="file"][data-preview]');
  if (!file) return;
  const image = document.getElementById(file.dataset.preview);
  const note = document.createElement("span");
  note.className = "muted";
  file.after(note);
  file.addEventListener("change", () => {
    const chosen = file.files[0];
    note.textContent = "";
    image.hidden = true;
    if (!chosen) return;
    if (chosen.size > Number(file.dataset.maxBytes)) note.textContent = "용량이 상한을 넘습니다. 그대로 보내면 거절됩니다.";
    const reader = new FileReader();
    image.onerror = () => { image.hidden = true; };  // 그림이 아닌 파일은 깨진 그림 대신 숨긴다(서버가 거절 사유를 알린다)
    reader.onload = () => { image.src = reader.result; image.hidden = false; };
    reader.readAsDataURL(chosen);
  });
})();
