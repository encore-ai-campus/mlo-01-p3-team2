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

  // 2) 고른 등록 소재 미리보기(제목·이동 주소·이미지는 서버가 그려 두고 고른 것만 보인다)
  const existing = form.querySelector('select[name="creative_id"]');
  const showExisting = () => {
    form.querySelectorAll(".creative-preview [data-creative]").forEach((el) => { el.hidden = el.dataset.creative !== (existing ? existing.value : ""); });
  };

  // 3) 아래 띠·확인 창의 요약(캠페인·구성·입찰·소재)
  const summary = document.getElementById("ad-summary");
  const line = document.getElementById("ad-summary-line");
  const value = (name) => (form.elements[name] ? form.elements[name].value.trim() : "");
  const refresh = () => {
    const campaign = form.elements.campaign_id;
    const slots = [...form.querySelectorAll('input[name="slot_ids"]:checked')].map((c) => c.closest("label").querySelector(".name").textContent);
    const bid = Number(value("bid_amount"));
    const source = (form.querySelector('input[name="creative_source"]:checked') || {}).value;
    const creative = source === "existing"
      ? (existing && existing.value ? existing.selectedOptions[0].textContent : "고르지 않음")
      : `${value("title") || "제목 없음"}(새로 올리기)`;
    const rows = [
      ["캠페인", campaign && campaign.selectedOptions[0] ? campaign.selectedOptions[0].textContent : "고르지 않음"],
      ["구성 · 입찰", `${slots.length ? slots.join(", ") : "구성 없음"} · ${bid > 0 ? `${bid.toLocaleString()} P` : "입찰 없음"}`],
      ["소재", creative],
    ];
    summary.replaceChildren(...rows.map(([term, text]) => {
      const row = document.createElement("div");
      const dt = document.createElement("dt"); dt.textContent = term;
      const dd = document.createElement("dd"); dd.textContent = text;
      row.append(dt, dd);
      return row;
    }));
    line.textContent = `선택 구성 ${slots.length}개 · 입찰 ${bid > 0 ? `${bid.toLocaleString()} P` : "없음"} · ${source === "existing" ? "등록된 소재" : "새 소재"}`;
    showExisting();
  };
  form.addEventListener("input", refresh);
  form.addEventListener("change", refresh);
  refresh();

  // 4) 올리기 전 이미지 미리보기와 용량 안내(막지는 않는다)
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
