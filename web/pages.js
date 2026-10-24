// ============================================================== Oggi, FTP e dettaglio non-corsa in neon
(() => {
  const { N, nxChart, ring, tier, el, markEl, failed } = window.nx;
  const { parseDay } = window.gx;
  const S = window.gxState;
  const f0 = d3.format('.0f');

  function drawToday() {
    if (S.page !== 'oggi') return;
    const w = dash.data('wellness');
    const host = document.getElementById('chart-rec60');
    if (w.status === 'error') { failed(host); return; }
    if (w.status !== 'ok') return;
    const rows = w.data.filter((r) => r.recovery != null);
    if (!rows.length) return;
    const last = parseDay(rows[rows.length - 1].date);
    const D = rows.map((r) => ({ ...r, _d: parseDay(r.date) })).filter((r) => r._d >= d3.utcDay.offset(last, -60));
    nxChart(host, {
      xType: 'time', height: 200, yDomain: [0, 100], yFmt: f0,
      series: [
        { type: 'dots', name: 'Recupero', color: N.cyan, r: 3.5, opacity: 0.6, data: D.map((r) => ({ x: r._d, y: r.recovery, label: r.recovery_label })) },
        { type: 'line', name: 'Media 7 gg', color: N.lime, data: D.map((r) => ({ x: r._d, y: r.recovery_7d })) },
      ],
    });
    // anello sul numero principale
    const big = document.querySelector('.gx-today-ring');
    const r = rows[rows.length - 1];
    big.querySelector('svg')?.remove();
    ring(big, r.recovery, 132, 10);
    big.prepend(big.lastChild);
  }

  function drawFtp() {
    if (S.page !== 'progressi') return;
    const a = dash.data('activities'), est = dash.data('ftp_est');
    const host = document.getElementById('chart-ftp');
    if (a.status === 'error') { failed(host); return; }
    if (a.status !== 'ok') return;
    const rides = a.data.filter((r) => r.sport === 'bike' && !r.duplicate && r.best_20min).map((r) => ({ ...r, _d: parseDay(r.date) })).sort((p, q) => p._d - q._d);
    nxChart(host, {
      xType: 'time', height: 240, yFmt: f0,
      series: [
        { type: 'line', name: 'FTP stimata', color: N.cyan, fmt: (v) => f0(v) + ' W', data: est.status === 'ok' ? est.data.map((r) => ({ x: parseDay(r.date), y: r.ftp_est })) : [] },
        { type: 'line', step: true, name: 'FTP Garmin', color: N.magenta, fmt: (v) => f0(v) + ' W', data: rides.filter((r) => r.ftp).map((r) => ({ x: r._d, y: r.ftp })) },
        { type: 'dots', name: "Miglior 20'", color: N.lime, fmt: (v) => f0(v) + ' W', data: rides.map((r) => ({ x: r._d, y: r.best_20min, label: r.name })) },
      ],
    });
  }

  function drawGeneric() {
    const det = document.getElementById('dettaglio-allenamento');
    if (det.hidden || S.page !== 'allenamenti') return;
    const a = dash.data('activities'), c = dash.data('components');
    if (a.status !== 'ok') return;
    const r = a.data.find((q) => q.id === S.sel);
    if (!r) return;
    const rg = det.querySelector('.nx-gen-ring');
    rg.querySelector('svg')?.remove();
    const t = ring(rg, r.score, 132, 10);
    rg.prepend(rg.lastChild);
    det.querySelector('.gx-det-score').className = 'gx-det-score ' + t.cls;
    det.querySelector('.nx-gen-tier').textContent = r.score == null ? 'senza voto' : t.label;
    const host = det.querySelector('.nx-gen-sections');
    const comps = c.status === 'ok' ? c.data.filter((q) => q.activity_id === r.id) : [];
    if (!comps.length) { host.replaceChildren(el('p', 'nx-note', r.sport === 'other' ? 'Sport non valutato: conta solo per il carico di allenamento.' : 'Componenti non disponibili.')); return; }
    host.replaceChildren(...comps.map((q) => {
      const card = el('div', 'nx-sec');
      const g = el('div'); const tt = ring(g, q.score, 56, 6);
      const right = el('div');
      const tag = el('div', 'nx-sec-tag ' + tt.cls);
      tag.append(markEl(el('span', null, q.score != null ? f0(q.score) : '—'), 'components', 'score', 'key=' + q.key),
        ` · ${tt.label} `, el('span', 'nx-sec-w', `peso ${q.weight}`));
      right.append(markEl(el('div', 'nx-sec-name', q.component), 'components', 'component', 'key=' + q.key), tag);
      const note = el('p', 'nx-sec-note');
      if (q.value != null) note.append('valore ', markEl(el('b', null, q.value), 'components', 'value', 'key=' + q.key), ' · ');
      note.append(markEl(el('span', null, q.note || ''), 'components', 'note', 'key=' + q.key));
      card.append(g, right, note);
      return card;
    }));
  }

  const drawAll = () => { drawToday(); drawFtp(); drawGeneric(); };
  const base = window.gxDraw;
  window.gxDraw = () => { base(); drawAll(); };
  dash.onData(drawAll);
})();
