// 광고 만들기의 편의 기능(설계 D3-1). 없어도 모든 흐름이 동작하고, 규칙은 여기 없다 — 서버(create_ad)가 다시 검증한다.
(() => {
  const form = document.querySelector("form.ad-create");
  if (!form) return;

  // 1) 글자 수(이름·제목 등 최대 길이가 있는 칸)
  form.querySelectorAll("input[maxlength]").forEach((input) => {
    const counter = document.createElement("span");
    counter.className = "muted counter";
    const update = () => { counter.textContent = `${input.value.length}/${input.maxLength}`; };
    input.after(counter);
    input.addEventListener("input", update);
    update();
  });

  // 2) 올리기 전 이미지 미리보기와 용량 안내(막지는 않는다)
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
