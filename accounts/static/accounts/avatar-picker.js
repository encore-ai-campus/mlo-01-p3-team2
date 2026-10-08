(() => {
  'use strict';
  const picker = document.querySelector('[data-avatar-picker]');
  if (!picker) return;
  const outfits = [...picker.querySelectorAll('.avatar-option')];
  const status = picker.querySelector('[data-avatar-status]');
  function update(announce = false) {
    for (const option of outfits) option.classList.toggle('is-selected', option.querySelector('input').checked);
    const active = outfits.find(option => option.querySelector('input').checked);
    if (announce && active) {
      status.textContent = `${active.querySelector('.avatar-type').textContent} · ${active.querySelector('strong').textContent} 선택됨`;
    }
  }
  picker.addEventListener('change', () => update(true));
  update();
})();
