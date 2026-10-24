// ---------------------------------------------------------------- navigazione e stato
window.gxState = { page: 'oggi', range: 180, sport: 'all', search: '', sort: { key: 'date', dir: -1 }, sel: null, env: 'out' };
(() => {
  const S = window.gxState;
  const tabs = [...document.querySelectorAll('.gx-tab')];
  const show = (id, link = true) => {
    if (!document.getElementById(id) || !tabs.some((t) => t.dataset.page === id)) return;
    S.page = id;
    tabs.forEach((t) => t.setAttribute('aria-selected', String(t.dataset.page === id)));
    document.querySelectorAll('.gx-page').forEach((p) => { p.hidden = p.id !== id; });
    if (link) dash.setLink(id);
    window.gxDraw && window.gxDraw();
  };
  tabs.forEach((t) => t.addEventListener('click', () => show(t.dataset.page)));
  const h = location.hash.slice(1);
  if (h) show(h, false);
  window.gxShow = show;

  document.querySelectorAll('[data-sport]').forEach((b) => b.addEventListener('click', () => { S.sport = b.dataset.sport; window.gxDraw(); }));
  document.querySelectorAll('[data-env]').forEach((b) => b.addEventListener('click', () => { S.env = b.dataset.env; window.gxDraw(); }));
  document.getElementById('cerca-allenamenti').addEventListener('input', (e) => { S.search = e.target.value.toLowerCase(); window.gxDraw(); });
  document.querySelectorAll('[data-sort]').forEach((b) => b.addEventListener('click', () => {
    const k = b.dataset.sort;
    S.sort = { key: k, dir: S.sort.key === k ? -S.sort.dir : (['name', 'sport_label'].includes(k) ? 1 : -1) };
    window.gxDraw();
  }));
  const pick = (ev) => {
    const tr = ev.target.closest('tr[data-key]');
    if (!tr) return;
    S.sel = tr.dataset.key;
    window.gxDraw();
    document.getElementById('dettaglio-allenamento').scrollIntoView({ block: 'nearest' });
  };
  const tb = document.querySelector('.gx-acts tbody');
  tb.addEventListener('click', pick);
  tb.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); } });
})();
