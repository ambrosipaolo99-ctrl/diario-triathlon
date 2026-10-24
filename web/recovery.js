// ============================================================== Recupero (neon)
(() => {
  const { N, MONO, nxChart, ring, tier, el, markEl, empty, failed, chips } = window.nx;
  const { loc, parseDay } = window.gx;
  const S = window.gxState;
  Object.assign(S, { recWeek: null, recRange: 365 });
  const f0 = d3.format('.0f'), f1 = d3.format('.1f'), f2 = d3.format('.2f');
  const fmtDay = loc.utcFormat('%-d %b');
  const fmtDayY = loc.utcFormat('%-d %b %Y');
  const AREAS = [
    ['hrv', 'HRV', 25, 'Media ln(rMSSD) vs baseline 60 gg e variabilità giornaliera'],
    ['rhr', 'FC a riposo', 10, 'Media della settimana vs baseline'],
    ['sleep_qty', 'Quantità di sonno', 15, 'Ore dormite rispetto al fabbisogno'],
    ['sleep_qual', 'Qualità del sonno', 15, 'Sleep Score e sonno profondo + REM'],
    ['sleep_reg', 'Regolarità del sonno', 5, "Costanza dell'orario di addormentamento"],
    ['stress', 'Stress ed energia', 10, 'Stress diurno e Body Battery ricaricata'],
    ['load', 'Equilibrio del carico', 15, 'Rapporto acuto:cronico e forma (TSB)'],
    ['resp', 'Segnali respiratori', 5, 'Respiro e SpO2 notturni vs baseline'],
  ];
  const clock = (m) => { if (m == null || !isFinite(m)) return '—'; const t = Math.round(m + 18 * 60) % 1440; return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };

  function weekBars(host, rows, sel, onPick) {
    host.replaceChildren();
    const W = host.clientWidth, H = 220;
    if (!W) return;
    if (!rows.length) { empty(host, 'Nessuna settimana con dati sufficienti.'); return; }
    const x = d3.scaleBand(rows.map((r) => r.week), [30, W - 4]).padding(0.22);
    const y = d3.scaleLinear([0, 100], [H - 24, 12]);
    const svg = d3.select(host).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);
    [0, 50, 65, 80, 100].forEach((t) => {
      svg.append('line').attr('x1', 30).attr('x2', W - 4).attr('y1', y(t)).attr('y2', y(t)).attr('stroke', N.line).attr('stroke-dasharray', t === 0 || t === 100 ? null : '3 4');
      svg.append('text').attr('x', 26).attr('y', y(t)).attr('dy', '0.32em').attr('text-anchor', 'end').attr('font-size', 11).attr('font-family', MONO).attr('fill', N.muted).text(t);
    });
    const bars = svg.selectAll(null).data(rows).join('rect').attr('class', 'nx-glow')
      .attr('x', (r) => x(r.week)).attr('width', x.bandwidth())
      .attr('y', (r) => y(r.score ?? 0)).attr('height', (r) => H - 24 - y(r.score ?? 0))
      .attr('rx', Math.min(4, x.bandwidth() / 2))
      .attr('fill', (r) => tier(r.score).color).style('color', (r) => tier(r.score).color)
      .attr('fill-opacity', (r) => r.week === sel ? 1 : r.complete ? 0.7 : 0.35)
      .attr('stroke', (r) => r.week === sel ? N.text : 'none').attr('stroke-width', 1.5)
      .style('cursor', 'pointer');
    const monthTicks = rows.filter((r, i) => i === 0 || r.week.slice(5, 7) !== rows[i - 1].week.slice(5, 7));
    const step = Math.max(1, Math.ceil(monthTicks.length / Math.floor(W / 48)));
    svg.selectAll(null).data(monthTicks.filter((_, i) => i % step === 0)).join('text')
      .attr('x', (r) => x(r.week) + x.bandwidth() / 2).attr('y', H - 6).attr('text-anchor', 'start')
      .attr('font-size', 11).attr('font-family', MONO).attr('fill', N.muted).text((r) => loc.utcFormat('%b')(parseDay(r.week)));
    const tip = el('div', 'nx-tip'); tip.hidden = true; host.append(tip);
    bars.on('pointerenter pointermove', (ev, r) => {
      const t = tier(r.score);
      const v = el('b', null, r.score != null ? f0(r.score) : '—'); v.style.color = t.color;
      tip.replaceChildren(el('div', 'd', `${fmtDay(parseDay(r.week))} – ${fmtDayY(parseDay(r.week_end))}${r.complete ? '' : ' (in corso)'}`),
        (() => { const d = el('div'); d.append('Recupero ', v, ` · ${r.label || 'n/d'}`); return d; })(),
        el('div', null, r.limiter ? `Limitante: ${r.limiter}` : ''));
      tip.hidden = false;
      const [mx] = d3.pointer(ev, host); const tw = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(W - tw, mx + 12)) + 'px'; tip.style.top = '6px';
    }).on('pointerleave', () => { tip.hidden = true; })
      .on('click', (ev, r) => onPick(r.week));
  }

  function draw() {
    if (S.page !== 'recupero') return;
    const box = document.getElementById('recupero');
    const wk = dash.data('recovery_weekly'), w = dash.data('wellness'), l = dash.data('load');
    if (wk.status === 'error') { failed(box.querySelector('#nx-rec-weeks')); return; }
    if (wk.status !== 'ok') return;
    const weeks = wk.data.filter((r) => r.score != null);
    if (!weeks.length) { empty(box.querySelector('#nx-rec-weeks'), 'Servono almeno due settimane di dati.'); return; }
    const current = weeks[weeks.length - 1];
    const lastFull = [...weeks].reverse().find((r) => r.complete) || current;
    if (!S.recWeek || !weeks.some((r) => r.week === S.recWeek)) S.recWeek = current.week;

    // intestazione: settimana in corso e ultima completa
    const hero = box.querySelector('.nx-rec-hero');
    const heroCard = (r, title) => {
      const c = el('div', 'nx-rec-hero-card');
      const rg = el('div', 'nx-ring'); const t = ring(rg, r.score, 132, 10); rg.prepend(rg.lastChild);
      const val = el('div', 'nx-ring-val');
      const b = markEl(el('b', t.cls, f0(r.score)), 'recovery_weekly', 'score', 'week=' + r.week);
      const lab = markEl(el('span', null, r.label), 'recovery_weekly', 'label', 'week=' + r.week);
      val.append(b, lab); rg.append(val);
      const txt = el('div', 'nx-title');
      txt.append(el('span', 'nx-eyebrow', title), el('h2', null, `${fmtDay(parseDay(r.week))} – ${fmtDayY(parseDay(r.week_end))}`));
      const lim = el('p', 'nx-note'); lim.append('Fattore limitante: ', markEl(el('b', null, r.limiter || '—'), 'recovery_weekly', 'limiter', 'week=' + r.week));
      txt.append(lim);
      if (!r.complete) txt.append(el('p', 'nx-note', `Settimana in corso: ${r.days} notti registrate finora.`));
      if (r.red_flag) { const p = el('p', 'nx-note nx-s-low', '⚠ HRV molto sotto e FC a riposo molto sopra la baseline nella stessa settimana: voto limitato a 45. Valuta uno scarico.'); txt.append(p); }
      c.append(rg, txt); return c;
    };
    hero.replaceChildren(...(current.week === lastFull.week ? [heroCard(current, 'Ultima settimana')] : [heroCard(current, 'Settimana in corso'), heroCard(lastFull, 'Ultima settimana completa')]));

    // barre settimanali
    weekBars(box.querySelector('#nx-rec-weeks'), wk.data, S.recWeek, (week) => { S.recWeek = week; draw(); });

    // dettaglio settimana selezionata
    const sel = wk.data.find((r) => r.week === S.recWeek);
    const where = 'week=' + sel.week;
    const det = box.querySelector('.nx-rec-detail-title');
    det.textContent = `Settimana ${fmtDay(parseDay(sel.week))} – ${fmtDayY(parseDay(sel.week_end))}`;
    box.querySelector('.nx-rec-areas').replaceChildren(...AREAS.map(([k, name, wgt, hint]) => {
      const v = sel['c_' + k];
      const card = el('div', 'nx-sec');
      const g = el('div'); const t = ring(g, v, 56, 6);
      const right = el('div');
      const tag = el('div', 'nx-sec-tag ' + t.cls);
      tag.append(markEl(el('span', null, v != null ? f0(v) : '—'), 'recovery_weekly', 'c_' + k, where), ` · ${t.label} `, el('span', 'nx-sec-w', `peso ${wgt}`));
      right.append(el('div', 'nx-sec-name', name), tag);
      const note = el('p', 'nx-sec-note', sel['n_' + k] || `${hint}: dati insufficienti questa settimana.`);
      if (sel['n_' + k]) markEl(note, 'recovery_weekly', 'n_' + k, where);
      card.append(g, right, note); return card;
    }));

    // grafici giornalieri
    box.querySelectorAll('[data-recrange]').forEach((b) => b.setAttribute('aria-pressed', String(+b.dataset.recrange === S.recRange)));
    if (w.status !== 'ok') { if (w.status === 'error') failed(box.querySelector('.nx-rec-daily')); return; }
    const since = d3.utcDay.offset(d3.utcDay.floor(new Date()), -S.recRange);
    const D = w.data.map((r) => ({ ...r, _d: parseDay(r.date) })).filter((r) => r._d >= since);
    const xDomain = [since, d3.utcDay.floor(new Date())];
    const P = (k) => D.map((r) => ({ x: r._d, y: r[k] }));
    const base = { xType: 'time', xDomain, height: 150 };
    const C = (id, o) => nxChart(box.querySelector('#' + id), { ...base, ...o });

    C('nx-r-hrv', { height: 190, yFmt: f0, series: [
      { type: 'band', color: N.lime, opacity: 0.14, data: D.map((r) => ({ x: r._d, y: r.hrv_norm_lo, y2: r.hrv_norm_hi })) },
      { type: 'dots', name: 'HRV notte', color: N.cyan, r: 3, opacity: 0.55, fmt: (v) => f0(v) + ' ms', data: P('hrv') },
      { type: 'line', name: 'Media 7 gg', color: N.cyan, fmt: (v) => f0(v) + ' ms', data: P('hrv_7d_ms') },
    ] });
    C('nx-r-cv', { yFmt: f1, refLines: [{ y: 6, label: '6%', color: N.amber }], series: [
      { type: 'line', name: 'CV 7 gg', color: N.amber, fmt: (v) => f1(v) + '%', data: P('hrv_cv7') },
    ] });
    C('nx-r-rhr', { yFmt: f0, series: [
      { type: 'line', name: 'Baseline 60 gg', color: N.muted, glow: false, width: 1.5, fmt: (v) => f1(v) + ' bpm', data: P('rhr_base') },
      { type: 'dots', name: 'FC a riposo', color: N.magenta, r: 3, opacity: 0.6, fmt: (v) => f0(v) + ' bpm', data: P('rhr') },
      { type: 'line', name: 'Media 7 gg', color: N.magenta, fmt: (v) => f1(v) + ' bpm', data: P('rhr_7d') },
    ] });
    C('nx-r-sleep', { yFmt: f0, zero: true, series: [
      { type: 'bars', name: 'Sonno', color: N.violet, fmt: (v) => f1(v) + ' h', data: P('sleep_h') },
      { type: 'line', name: 'Fabbisogno', color: N.lime, width: 1.5, fmt: (v) => f1(v) + ' h', data: P('sleep_need_h') },
    ] });
    C('nx-r-score', { yDomain: [0, 100], yFmt: f0, series: [
      { type: 'dots', name: 'Sleep Score', color: N.cyan, r: 3, opacity: 0.55, data: P('sleep_score') },
      { type: 'line', name: 'Media 7 gg', color: N.cyan, data: P('sleep_score_7d') },
    ] });
    C('nx-r-stages', { yFmt: f0, series: [
      { type: 'line', name: 'Profondo', color: N.violet, fmt: (v) => f0(v) + '%', data: P('deep_pct') },
      { type: 'line', name: 'REM', color: N.magenta, fmt: (v) => f0(v) + '%', data: P('rem_pct') },
    ] });
    C('nx-r-bed', { yFmt: clock, yInvert: true, series: [
      { type: 'dots', name: 'Addormentamento', color: N.amber, r: 3, fmt: clock, data: P('bedtime_min') },
    ] });
    C('nx-r-resp', { yFmt: f1, series: [
      { type: 'line', name: 'Baseline', color: N.muted, glow: false, width: 1.5, fmt: (v) => f1(v) + '/min', data: P('resp_base') },
      { type: 'dots', name: 'Respiro', color: N.lime, r: 3, fmt: (v) => f1(v) + '/min', data: P('resp') },
    ] });
    C('nx-r-spo2', { yFmt: f0, series: [{ type: 'dots', name: 'SpO2', color: N.cyan, r: 3, fmt: (v) => f1(v) + '%', data: P('spo2') }] });
    C('nx-r-bb', { yFmt: f0, zero: true, series: [{ type: 'bars', name: 'Ricarica notturna', color: N.lime, fmt: f0, data: P('bb_charge') }] });
    C('nx-r-stress', { yFmt: f0, series: [
      { type: 'dots', name: 'Stress diurno', color: N.pink, r: 3, data: P('stress') },
      { type: 'line', name: 'Stress nel sonno', color: N.violet, width: 1.5, data: P('sleep_stress') },
    ] });
    if (l.status === 'ok') {
      const L = l.data.map((r) => ({ ...r, _d: parseDay(r.date) })).filter((r) => r._d >= since);
      const LP = (k) => L.map((r) => ({ x: r._d, y: r[k] }));
      C('nx-r-load', { height: 190, yFmt: f0, zero: true, series: [
        { type: 'bars', name: 'TSS', color: N.violet, data: LP('tss').map((p) => ({ ...p, y: p.y || null })) },
        { type: 'line', name: 'Cronico (CTL)', color: N.cyan, data: LP('ctl') },
        { type: 'line', name: 'Acuto (ATL)', color: N.magenta, data: LP('atl') },
      ] });
      C('nx-r-acwr', { yFmt: f2, refLines: [{ y: 0.8, label: '0,8', color: N.lime }, { y: 1.3, label: '1,3', color: N.amber }], series: [
        { type: 'line', name: 'Acuto:cronico', color: N.amber, fmt: f2, data: LP('acwr') },
      ] });
      C('nx-r-tsb', { yFmt: f0, refLines: [{ y: 0, color: N.muted }], series: [
        { type: 'area', name: 'Forma (TSB)', color: N.lime, data: LP('tsb') },
      ] });
    } else if (l.status === 'error') ['nx-r-load', 'nx-r-acwr', 'nx-r-tsb'].forEach((id) => failed(box.querySelector('#' + id)));
    C('nx-r-index', { yDomain: [0, 100], yFmt: f0, series: [
      { type: 'dots', name: 'Indice giornaliero', color: N.cyan, r: 3, opacity: 0.55, data: P('recovery') },
      { type: 'line', name: 'Media 7 gg', color: N.lime, data: P('recovery_7d') },
    ] });
  }

  document.querySelectorAll('[data-recrange]').forEach((b) => b.addEventListener('click', () => { S.recRange = +b.dataset.recrange; draw(); }));
  const base = window.gxDraw;
  window.gxDraw = () => { base(); draw(); };
  dash.onData(draw);
})();
