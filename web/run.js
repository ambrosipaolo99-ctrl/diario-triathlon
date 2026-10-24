// ============================================================== Corsa: calcoli derivati
// Medie mobili e riepiloghi mostrati nei grafici dei progressi.
dash.calc('run_hr_trend', {
  inputs: ['run_hr_pace'],
  title: 'Passo a parita di FC, media 42 gg',
  description: 'Per ogni fascia di FC e ambiente: media del passo nelle corse dei 42 giorni precedenti (inclusa la corsa).',
  fn: (run_hr_pace) => {
    const rows = run_hr_pace.map((r) => ({ ...r, t: Date.parse(r.date) })).sort((a, b) => a.t - b.t);
    return rows.map((r) => {
      const w = rows.filter((q) => q.env === r.env && q.hr_bin === r.hr_bin && q.t <= r.t && r.t - q.t < 42 * 864e5);
      return { key: r.key, date: r.date, env: r.env, hr_bin: r.hr_bin, pace_trend: Math.round(w.reduce((s, q) => s + q.pace_s, 0) / w.length * 10) / 10 };
    });
  },
});
dash.calc('run_hr_summary', {
  inputs: ['run_hr_trend'],
  title: 'Passo a parita di FC: oggi vs 90 gg fa',
  description: 'Per fascia di FC e ambiente: ultimo valore della media 42 gg e valore di circa 90 giorni prima; delta in secondi al km (negativo = piu veloce).',
  fn: (run_hr_trend) => {
    const groups = {};
    run_hr_trend.forEach((r) => { (groups[r.env + '-' + r.hr_bin] ||= []).push(r); });
    return Object.entries(groups).map(([key, g]) => {
      g.sort((a, b) => Date.parse(a.date) - Date.parse(b.date));
      const last = g[g.length - 1];
      const target = Date.parse(last.date) - 90 * 864e5;
      const before = g.filter((r) => Date.parse(r.date) <= target).pop() || null;
      return { key, env: last.env, hr_bin: last.hr_bin, n: g.length, pace_now: last.pace_trend,
        pace_before: before ? before.pace_trend : null,
        delta_s: before ? Math.round((last.pace_trend - before.pace_trend) * 10) / 10 : null };
    });
  },
});
dash.calc('run_dyn_trend', {
  inputs: ['run_pace_dyn'],
  title: 'Dinamiche a parita di passo, media 42 gg',
  description: 'Per fascia di passo e ambiente: media 42 gg di cadenza, contatto al suolo, oscillazione, rapporto verticale, lunghezza passo e FC.',
  fn: (run_pace_dyn) => {
    const rows = run_pace_dyn.map((r) => ({ ...r, t: Date.parse(r.date) })).sort((a, b) => a.t - b.t);
    const keys = ['cad', 'gct', 'vo', 'vr', 'step', 'hr'];
    return rows.map((r) => {
      const w = rows.filter((q) => q.env === r.env && q.pace_bin === r.pace_bin && q.t <= r.t && r.t - q.t < 42 * 864e5);
      const out = { key: r.key, date: r.date, env: r.env, pace_bin: r.pace_bin };
      keys.forEach((k) => { const v = w.map((q) => q[k]).filter((x) => x != null); out[k + '_t'] = v.length ? Math.round(v.reduce((s, x) => s + x, 0) / v.length * 1000) / 1000 : null; });
      return out;
    });
  },
});
dash.calc('run_trend', {
  inputs: ['runs'],
  title: 'Metriche corsa, media 28 gg',
  description: 'Per ambiente: media 28 gg di Efficiency Factor e deriva (solo corse continue >= 20 min) e dei voti di ogni sezione.',
  fn: (runs) => {
    const rows = runs.map((r) => ({ ...r, t: Date.parse(r.start) })).sort((a, b) => a.t - b.t);
    const keys = ['ef', 'decoupling_pct', 's_intensity', 's_efficiency', 's_pacing', 's_cadence', 's_contact', 's_vertical', 's_fatigue'];
    return rows.map((r) => {
      const w = rows.filter((q) => q.env === r.env && q.t <= r.t && r.t - q.t < 28 * 864e5);
      const out = { id: r.id, date: r.date, env: r.env };
      keys.forEach((k) => {
        const src = (k === 'ef' || k === 'decoupling_pct') ? w.filter((q) => q.steady && q.moving_min >= 20) : w;
        const v = src.map((q) => q[k]).filter((x) => x != null);
        out[k + '_t'] = v.length ? Math.round(v.reduce((s, x) => s + x, 0) / v.length * 1000) / 1000 : null;
      });
      return out;
    });
  },
});
dash.calc('run_weekly', {
  inputs: ['runs'],
  title: 'Volume di corsa settimanale',
  description: 'Chilometri, minuti e numero di corse per settimana (lunedi-domenica), outdoor e tapis roulant insieme.',
  fn: (runs) => {
    const weeks = {};
    runs.forEach((r) => {
      const d = new Date(r.date + 'T00:00:00Z');
      d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
      const k = d.toISOString().slice(0, 10);
      const w = (weeks[k] ||= { week: k, km: 0, minutes: 0, n: 0 });
      w.km += r.distance_km || 0; w.minutes += r.moving_min || 0; w.n += 1;
    });
    return Object.values(weeks).map((w) => ({ ...w, km: Math.round(w.km * 10) / 10, minutes: Math.round(w.minutes) }))
      .sort((a, b) => a.week.localeCompare(b.week));
  },
});

// ============================================================== Corsa: disegno neon
(() => {
  const { loc, parseDay, parseTs, fmtDayTime } = window.gx;
  const S = window.gxState;
  Object.assign(S, { runEnv: 'out', hrBin: null, paceBin: null });
  const N = { cyan: '#22e5ff', magenta: '#ff3df2', lime: '#b4ff39', amber: '#ffb22e', violet: '#9b7bff', pink: '#ff4d7d', muted: '#8391b8', line: '#1c2746', panel: '#0c1120', text: '#e8f1ff' };
  const MONO = 'ui-monospace, Cascadia Mono, SF Mono, Consolas, monospace';
  const f0 = d3.format('.0f'), f1 = d3.format('.1f'), f2 = d3.format('.2f'), f3 = d3.format('.3f');
  const signed = (v, fmt = f1) => (v > 0 ? '+' : '') + fmt(v);
  const paceFmt = (s) => { if (s == null || !isFinite(s)) return '—'; const t = Math.round(s); return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, '0')}`; };
  const hm = (min) => { if (min == null) return '—'; const t = Math.round(min); return t >= 60 ? `${Math.floor(t / 60)}h${String(t % 60).padStart(2, '0')}` : `${t}'`; };
  const tier = (v) => v == null ? { cls: '', label: 'n/d', color: N.muted }
    : v >= 80 ? { cls: 'nx-s-top', label: 'Ottimo', color: N.lime }
    : v >= 65 ? { cls: 'nx-s-good', label: 'Buono', color: N.cyan }
    : v >= 50 ? { cls: 'nx-s-mid', label: 'Da migliorare', color: N.amber }
    : { cls: 'nx-s-low', label: 'Critico', color: N.pink };
  const SECTIONS = [
    ["Controllo intensita'", 'Controllo intensità', 's_intensity'],
    ['Efficienza aerobica', 'Efficienza aerobica', 's_efficiency'],
    ['Gestione del ritmo', 'Gestione del ritmo', 's_pacing'],
    ['Cadenza', 'Cadenza', 's_cadence'],
    ['Contatto al suolo', 'Contatto al suolo', 's_contact'],
    ['Rimbalzo verticale', 'Rimbalzo verticale', 's_vertical'],
    ['Resistenza alla fatica', 'Resistenza alla fatica', 's_fatigue'],
  ];
  const ZONE_COLORS = [N.muted, N.cyan, N.lime, N.amber, N.pink];
  let gid = 0;
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const markEl = (e, src, field, where) => { e.setAttribute('data-source', src); if (field) e.setAttribute('data-field', field); if (where) e.setAttribute('data-where', where); return e; };
  const empty = (host, msg) => { host.replaceChildren(el('div', 'nx-empty', msg)); };
  const failed = (host) => { host.replaceChildren(el('div', 'gx-fail', 'Failed to load')); };

  // ------------------------------------------------------------ anello del voto
  function ring(host, value, size, stroke) {
    const t = tier(value);
    const r = (size - stroke) / 2, c = 2 * Math.PI * r;
    const svg = d3.select(host).append('svg').attr('viewBox', `0 0 ${size} ${size}`);
    svg.append('circle').attr('cx', size / 2).attr('cy', size / 2).attr('r', r).attr('fill', 'none').attr('stroke', N.line).attr('stroke-width', stroke);
    svg.append('circle').attr('class', 'arc nx-glow').style('color', t.color)
      .attr('cx', size / 2).attr('cy', size / 2).attr('r', r).attr('fill', 'none').attr('stroke', t.color).attr('stroke-width', stroke)
      .attr('stroke-linecap', 'round').attr('transform', `rotate(-90 ${size / 2} ${size / 2})`)
      .attr('stroke-dasharray', c).attr('stroke-dashoffset', c * (1 - (value ?? 0) / 100));
    return t;
  }

  // ------------------------------------------------------------ grafico neon generico
  function nxChart(host, o) {
    host.replaceChildren();
    const W = host.clientWidth;
    if (!W) return;
    const H = o.height || 170;
    const all = o.series.flatMap((s) => s.type === 'band' ? s.data.flatMap((p) => [p, { x: p.x, y: p.y2 }]) : s.data)
      .filter((p) => p.y != null && isFinite(p.y) && p.x != null);
    if (!all.length) { empty(host, o.empty || 'Nessun dato per questa selezione.'); return; }
    const isTime = o.xType === 'time';
    let xd = o.xDomain || d3.extent(all, (p) => p.x);
    if (+xd[0] === +xd[1]) xd = isTime ? [new Date(+xd[0] - 864e5 * 7), new Date(+xd[1] + 864e5 * 7)] : [xd[0] - 1, xd[1] + 1];
    let [lo, hi] = o.yDomain || d3.extent(all, (p) => p.y);
    if (!o.yDomain) { const pad = (hi - lo) * 0.12 || Math.abs(hi) * 0.05 || 1; lo -= pad; hi += pad; if (o.zero) lo = Math.min(0, lo); }
    const y = d3.scaleLinear([lo, hi], o.yInvert ? [10, H - 22] : [H - 22, 10]).nice(4);
    const yFmt = o.yFmt || f0;
    const ticks = y.ticks(4);
    const svg = d3.select(host).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);
    const probe = svg.append('text').attr('font-size', 11).attr('font-family', MONO);
    const ml = 10 + (d3.max(ticks, (t) => { probe.text(yFmt(t)); return probe.node().getComputedTextLength(); }) || 20);
    probe.remove();
    const x = (isTime ? d3.scaleUtc : d3.scaleLinear)(xd, [ml, W - 8]);
    const g = svg.append('g');
    g.selectAll(null).data(ticks).join('line').attr('x1', ml).attr('x2', W - 8).attr('y1', (t) => y(t)).attr('y2', (t) => y(t)).attr('stroke', N.line);
    g.selectAll(null).data(ticks).join('text').attr('x', ml - 6).attr('y', (t) => y(t)).attr('dy', '0.32em').attr('text-anchor', 'end')
      .attr('font-size', 11).attr('font-family', MONO).attr('fill', N.muted).text(yFmt);
    const xt = x.ticks(Math.max(2, Math.floor(W / 90)));
    const xFmt = o.xFmt || (isTime ? loc.utcFormat('%-d %b') : (v) => `${f0(v)} km`);
    g.selectAll(null).data(xt).join('text').attr('x', (t) => x(t)).attr('y', H - 5).attr('text-anchor', 'middle')
      .attr('font-size', 11).attr('font-family', MONO).attr('fill', N.muted).text(xFmt);
    (o.refLines || []).forEach((r) => {
      if (r.y == null || r.y < Math.min(...y.domain()) || r.y > Math.max(...y.domain())) return;
      g.append('line').attr('x1', ml).attr('x2', W - 8).attr('y1', y(r.y)).attr('y2', y(r.y)).attr('stroke', r.color || N.muted).attr('stroke-opacity', 0.7).attr('stroke-dasharray', '4 4');
      if (r.label) g.append('text').attr('x', W - 10).attr('y', y(r.y) - 4).attr('text-anchor', 'end').attr('font-size', 11).attr('font-family', MONO).attr('fill', r.color || N.muted).text(r.label);
    });
    const defs = svg.append('defs');
    for (const s of o.series) {
      const d = s.data.filter((p) => p.x != null);
      const line = d3.line().defined((p) => p.y != null && isFinite(p.y)).x((p) => x(p.x)).y((p) => y(p.y)).curve(s.step ? d3.curveStepAfter : d3.curveLinear);
      if (s.type === 'band') {
        g.append('path').datum(d).attr('fill', s.color).attr('fill-opacity', s.opacity ?? 0.12)
          .attr('d', d3.area().defined((p) => p.y != null && p.y2 != null && isFinite(p.y) && isFinite(p.y2)).x((p) => x(p.x)).y0((p) => y(p.y)).y1((p) => y(p.y2)));
        continue;
      }
      if (s.type === 'area') {
        const id = 'nxg' + (++gid);
        const gr = defs.append('linearGradient').attr('id', id).attr('x1', 0).attr('x2', 0).attr('y1', 0).attr('y2', 1);
        [[0, 0.38], [0.5, 0.12], [1, 0]].forEach(([off, op]) => gr.append('stop').attr('offset', off).style('stop-color', s.color).style('stop-opacity', op));
        const base = o.yInvert ? y.range()[1] : y.range()[0];
        g.append('path').datum(d).attr('fill', `url(#${id})`)
          .attr('d', d3.area().defined((p) => p.y != null && isFinite(p.y)).x((p) => x(p.x)).y0(base).y1((p) => y(p.y)));
      }
      if (s.type === 'area' || s.type === 'line') {
        g.append('path').datum(d).attr('class', s.glow === false ? '' : 'nx-glow').style('color', s.color).attr('fill', 'none').attr('stroke', s.color)
          .attr('stroke-width', s.width || 2).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round').attr('opacity', s.opacity ?? 1).attr('d', line);
      } else if (s.type === 'dots') {
        g.selectAll(null).data(d.filter((p) => p.y != null)).join('circle').attr('cx', (p) => x(p.x)).attr('cy', (p) => y(p.y)).attr('r', s.r || 4)
          .attr('fill', s.color).attr('fill-opacity', s.opacity ?? 0.75).attr('stroke', N.panel).attr('stroke-width', 1.5);
      } else if (s.type === 'bars') {
        const bw = Math.max(2, Math.min(18, (W - ml) / Math.max(8, d.length) * 0.65));
        const y0 = y(Math.max(Math.min(0, y.domain()[1]), y.domain()[0]));
        g.selectAll(null).data(d.filter((p) => p.y != null)).join('rect').attr('x', (p) => x(p.x) - bw / 2).attr('width', bw)
          .attr('y', (p) => Math.min(y(p.y), y0)).attr('height', (p) => Math.abs(y0 - y(p.y))).attr('rx', Math.min(3, bw / 2))
          .attr('fill', s.color).attr('fill-opacity', 0.85).attr('class', 'nx-glow').style('color', s.color);
      }
    }
    // tooltip sul punto piu' vicino
    const tip = el('div', 'nx-tip'); tip.hidden = true; host.append(tip);
    const rule = g.append('line').attr('y1', 10).attr('y2', H - 22).attr('stroke', N.muted).attr('stroke-opacity', 0);
    const named = o.series.filter((s) => s.name);
    const xs = [...new Set(named.flatMap((s) => s.data.filter((p) => p.y != null).map((p) => +p.x)))].sort((a, b) => a - b);
    const bis = d3.bisector((v) => v).center;
    const tipHead = o.tipX || (isTime ? (v) => window.gx.fmtDay(new Date(v)) : (v) => `km ${f2(v)}`);
    svg.append('rect').attr('x', ml).attr('y', 0).attr('width', Math.max(0, W - ml)).attr('height', H).attr('fill', 'transparent')
      .on('pointermove', (ev) => {
        if (!xs.length) return;
        const [mx] = d3.pointer(ev);
        const t = xs[bis(xs, +x.invert(mx))];
        const lines = named.map((s) => {
          const p = s.data.find((q) => +q.x === t && q.y != null);
          if (!p) return null;
          const row = el('div');
          const sw = el('span', 'sw'); sw.style.background = s.color; sw.style.color = s.color;
          row.append(sw, s.name + ' ', el('b', null, (s.fmt || yFmt)(p.y)), p.label ? ' · ' + p.label : '');
          return row;
        }).filter(Boolean);
        if (!lines.length) { tip.hidden = true; return; }
        tip.replaceChildren(el('div', 'd', tipHead(t)), ...lines);
        tip.hidden = false;
        rule.attr('x1', x(t)).attr('x2', x(t)).attr('stroke-opacity', 0.6);
        const tw = tip.offsetWidth;
        tip.style.left = Math.max(0, Math.min(W - tw, x(t) + 12 + tw > W ? x(t) - tw - 12 : x(t) + 12)) + 'px';
        tip.style.top = '6px';
      })
      .on('pointerleave', () => { tip.hidden = true; rule.attr('stroke-opacity', 0); });
  }

  // ------------------------------------------------------------ split per km
  function splitBars(host, rows) {
    host.replaceChildren();
    const W = host.clientWidth, H = 200;
    if (!W) return;
    if (!rows.length) { empty(host, 'Split non disponibili.'); return; }
    const x = d3.scaleBand(rows.map((r) => r.km), [34, W - 4]).padding(0.25);
    const sp = rows.map((r) => 1000 / r.pace_s);
    const y = d3.scaleLinear([d3.min(sp) * 0.92, d3.max(sp) * 1.02], [H - 22, 22]);
    const hrs = rows.map((r) => r.hr).filter((v) => v != null);
    const hrScale = hrs.length ? d3.scaleLinear([d3.min(hrs), d3.max(hrs) || d3.min(hrs) + 1], [0, 1]) : null;
    const col = (r) => hrScale && r.hr != null ? d3.interpolateRgb(N.cyan, N.magenta)(hrScale(r.hr) || 0) : N.cyan;
    const svg = d3.select(host).append('svg').attr('width', '100%').attr('height', H).attr('viewBox', `0 0 ${W} ${H}`);
    const yt = y.ticks(3);
    svg.selectAll(null).data(yt).join('line').attr('x1', 34).attr('x2', W - 4).attr('y1', (t) => y(t)).attr('y2', (t) => y(t)).attr('stroke', N.line);
    svg.selectAll(null).data(yt).join('text').attr('x', 30).attr('y', (t) => y(t)).attr('dy', '0.32em').attr('text-anchor', 'end')
      .attr('font-size', 11).attr('font-family', MONO).attr('fill', N.muted).text((t) => paceFmt(1000 / t));
    const bars = svg.selectAll(null).data(rows).join('rect').attr('class', 'nx-glow')
      .attr('x', (r) => x(r.km)).attr('width', x.bandwidth()).attr('y', (r) => y(1000 / r.pace_s)).attr('height', (r) => Math.max(1, H - 22 - y(1000 / r.pace_s)))
      .attr('rx', Math.min(4, x.bandwidth() / 2)).attr('fill', col).style('color', col).attr('fill-opacity', (r) => r.partial ? 0.45 : 0.9);
    if (x.bandwidth() >= 30) {
      svg.selectAll(null).data(rows).join('text').attr('x', (r) => x(r.km) + x.bandwidth() / 2).attr('y', (r) => y(1000 / r.pace_s) - 6)
        .attr('text-anchor', 'middle').attr('font-size', 11).attr('font-family', MONO).attr('fill', N.text).text((r) => paceFmt(r.pace_s));
    }
    const step = Math.max(1, Math.ceil(rows.length / Math.floor(W / 28)));
    svg.selectAll(null).data(rows.filter((_, i) => i % step === 0)).join('text').attr('x', (r) => x(r.km) + x.bandwidth() / 2).attr('y', H - 6)
      .attr('text-anchor', 'middle').attr('font-size', 11).attr('font-family', MONO).attr('fill', N.muted).text((r) => r.km);
    const tip = el('div', 'nx-tip'); tip.hidden = true; host.append(tip);
    bars.on('pointerenter pointermove', (ev, r) => {
      const parts = [el('div', 'd', `km ${r.km}${r.partial ? ' (parziale)' : ''}`), el('div', null, `Passo ${paceFmt(r.pace_s)}/km`)];
      if (r.hr != null) parts.push(el('div', null, `FC ${f0(r.hr)} bpm`));
      if (r.cad != null) parts.push(el('div', null, `Cadenza ${f0(r.cad)} passi/min`));
      if (r.gct != null) parts.push(el('div', null, `Contatto ${f0(r.gct)} ms`));
      if (r.elev_gain_m != null) parts.push(el('div', null, `Dislivello +${f0(r.elev_gain_m)} m`));
      tip.replaceChildren(...parts); tip.hidden = false;
      const [mx] = d3.pointer(ev, host);
      const tw = tip.offsetWidth;
      tip.style.left = Math.max(0, Math.min(W - tw, mx + 12)) + 'px'; tip.style.top = '6px';
      bars.attr('fill-opacity', (q) => q === r ? 1 : 0.35);
    }).on('pointerleave', () => { tip.hidden = true; bars.attr('fill-opacity', (q) => q.partial ? 0.45 : 0.9); });
  }

  // ------------------------------------------------------------ report della singola corsa
  const DYN = [
    { k: 'cad', name: 'Cadenza', unit: 'passi/min', color: N.lime, avg: 'cadence', fat: 'fatigue_cad_pct', fmt: f0 },
    { k: 'gct', name: 'Contatto al suolo', unit: 'ms', color: N.amber, avg: 'gct', fat: 'fatigue_gct_pct', fmt: f0 },
    { k: 'vo', name: 'Oscillazione verticale', unit: 'cm', color: N.violet, avg: 'vo_cm', fat: 'fatigue_vo_pct', fmt: f1 },
    { k: 'vr', name: 'Rapporto verticale', unit: '%', color: N.cyan, avg: 'vr', fmt: f1 },
    { k: 'step', name: 'Lunghezza del passo', unit: 'm', color: N.magenta, avg: 'step_m', fat: 'fatigue_step_pct', fmt: f2 },
  ];

  function drawRunReport() {
    const box = document.getElementById('report-corsa');
    const generic = document.getElementById('dettaglio-allenamento');
    const acts = dash.data('activities');
    const sel = acts.status === 'ok' ? acts.data.find((a) => a.id === S.sel) : null;
    const isRun = !!sel && sel.sport === 'run';
    box.hidden = !isRun || S.page !== 'allenamenti';
    generic.hidden = isRun;
    if (box.hidden) return;
    const runs = dash.data('runs'), comps = dash.data('components'), stream = dash.data('run_stream'), splits = dash.data('run_splits');
    if (runs.status === 'error') { failed(box.querySelector('.nx-sections')); return; }
    if (runs.status !== 'ok') return;
    const r = runs.data.find((q) => q.id === S.sel);
    if (!r) { box.querySelector('.nx-coach').textContent = 'Questa corsa non ha ancora il dettaglio: verrà incluso al prossimo aggiornamento.'; return; }
    const where = 'id=' + r.id;

    // intestazione
    box.querySelector('.nx-run-name').textContent = r.name;
    markEl(box.querySelector('.nx-run-name'), 'runs', 'name', where);
    const dt = box.querySelector('.nx-run-date'); markEl(dt, 'runs', 'start', where);
    dt.textContent = fmtDayTime(parseTs(r.start)) + (r.env === 'in' ? ' · tapis roulant' : '');
    const ringHost = box.querySelector('.nx-ring');
    ringHost.querySelector('svg')?.remove();
    const t = ring(ringHost, r.score, 132, 10);
    ringHost.prepend(ringHost.lastChild);
    const val = ringHost.querySelector('.nx-ring-val b');
    markEl(val, 'runs', 'score', where); val.textContent = r.score ?? '—'; val.className = t.cls;
    ringHost.querySelector('.nx-ring-val span').textContent = t.label;

    const stats = [
      ['Distanza', 'distance_km', (v) => f2(v) + ' km'], ['Tempo', 'moving_min', hm], ['Passo', 'pace_s', (v) => paceFmt(v) + '/km'],
      ['Dislivello', 'ascent_m', (v) => `+${f0(v)} m${r.ascent_source === 'strava' ? ' (Strava)' : ''}`],
      ['FC media', 'avg_hr', (v) => f0(v) + ' bpm'], ['FC max', 'max_hr', (v) => f0(v) + ' bpm'], ['Cadenza', 'cadence', (v) => f0(v) + ' ppm'],
      ['Contatto', 'gct', (v) => f0(v) + ' ms'], ['Efficiency Factor', 'ef', f2], ['VO2max Garmin', 'vo2max', f0],
    ];
    box.querySelector('.nx-stats').replaceChildren(...stats.filter(([, k]) => r[k] != null).map(([label, k, fmt]) => {
      const d = el('div', 'nx-stat'); const b = markEl(el('b', null, fmt(r[k])), 'runs', k, where);
      d.append(el('span', null, label), b); return d;
    }));

    // sezioni del voto
    const secHost = box.querySelector('.nx-sections');
    const rows = comps.status === 'ok' ? comps.data.filter((c) => c.activity_id === r.id) : [];
    const byName = Object.fromEntries(rows.map((c) => [c.component, c]));
    const scored = [];
    secHost.replaceChildren(...SECTIONS.map(([key, label]) => {
      const c = byName[key];
      const card = el('div', 'nx-sec');
      const g = el('div'); const tt = ring(g, c ? c.score : null, 56, 6);
      const right = el('div');
      const name = el('div', 'nx-sec-name', label);
      const tag = el('div', 'nx-sec-tag ' + tt.cls);
      const sc = el('span', null, c && c.score != null ? f0(c.score) : '—');
      if (c) markEl(sc, 'components', 'score', 'key=' + c.key);
      tag.append(sc, ` · ${tt.label} `, el('span', 'nx-sec-w', `peso ${c ? c.weight : '—'}`));
      right.append(name, tag);
      const note = el('p', 'nx-sec-note', c ? (c.note || '') : 'Non calcolata per questa corsa.');
      if (c) markEl(note, 'components', 'note', 'key=' + c.key);
      card.append(g, right, note);
      if (c && c.score != null) scored.push([label, c.score]);
      return card;
    }));
    const coach = box.querySelector('.nx-coach');
    if (scored.length) {
      scored.sort((a, b) => b[1] - a[1]);
      const best = scored[0][0], worst = scored[scored.length - 1][0];
      coach.replaceChildren('Lettura del coach: punto forte ', el('b', null, best.toLowerCase()), ', da lavorare ', el('b', null, worst.toLowerCase()),
        r.steady ? '. Corsa continua: contano soprattutto deriva cardiaca e tenuta del gesto nel finale.' : '. Sessione a ripetute: contano regolarità delle ripetute e qualità del gesto nei tratti veloci.');
    } else coach.textContent = 'Sezioni non disponibili per questa corsa.';

    // grafici su distanza
    const pts = stream.status === 'ok' ? stream.data.filter((p) => p.activity_id === r.id) : [];
    const X = (p) => p.dist_km;
    nxChart(document.getElementById('nx-chart-pace'), {
      height: 180, yInvert: true, yFmt: paceFmt, empty: 'Serie non disponibile.',
      refLines: [{ y: r.pace_s, label: 'media ' + paceFmt(r.pace_s), color: N.cyan }],
      series: [{ type: 'area', name: 'Passo', color: N.cyan, fmt: (v) => paceFmt(v) + '/km', data: pts.map((p) => ({ x: X(p), y: p.pace_s })) }],
    });
    nxChart(document.getElementById('nx-chart-hr'), {
      height: 150, yFmt: f0,
      refLines: [{ y: r.avg_hr, label: 'media ' + f0(r.avg_hr ?? 0), color: N.magenta }],
      series: [{ type: 'area', name: 'FC', color: N.magenta, fmt: (v) => f0(v) + ' bpm', data: pts.map((p) => ({ x: X(p), y: p.hr })) }],
    });
    const altCard = document.getElementById('nx-alt-card');
    altCard.hidden = !r.altitude_reliable || r.env === 'in' || !pts.some((p) => p.alt != null);
    if (!altCard.hidden) nxChart(document.getElementById('nx-chart-alt'), {
      height: 110, yFmt: f0, series: [{ type: 'area', name: 'Quota', color: N.violet, fmt: (v) => f0(v) + ' m', data: pts.map((p) => ({ x: X(p), y: p.alt })) }],
    });

    // dinamiche
    const dynHost = box.querySelector('.nx-dyn');
    dynHost.replaceChildren(...DYN.filter((m) => pts.some((p) => p[m.k] != null)).map((m) => {
      const card = el('div', 'nx-card');
      const head = el('div', 'nx-card-head');
      const v = markEl(el('span', 'nx-card-val', r[m.avg] != null ? `${m.fmt(r[m.avg])} ${m.unit}` : '—'), 'runs', m.avg, where);
      v.style.color = m.color;
      head.append(el('h3', null, m.name), v);
      card.append(head);
      if (m.fat && r[m.fat] != null) {
        const bad = m.k === 'gct' || m.k === 'vo' ? r[m.fat] > 3 : r[m.fat] < -3;
        const chip = markEl(el('span', 'nx-chip-delta', `ultimo terzo ${signed(r[m.fat])}%`), 'runs', m.fat, where);
        chip.style.color = bad ? N.pink : N.muted;
        const note = el('p', 'nx-note'); note.append(chip);
        card.append(note);
      }
      const ch = el('div', 'nx-chart'); card.append(ch);
      requestAnimationFrame(() => nxChart(ch, {
        height: 110, yFmt: m.k === 'step' ? f2 : m.k === 'vo' || m.k === 'vr' ? f1 : f0,
        series: [{ type: 'line', name: m.name, color: m.color, fmt: (q) => `${m.fmt(q)} ${m.unit}`, data: pts.map((p) => ({ x: X(p), y: p[m.k] })) }],
      }));
      return card;
    }));
    if (!dynHost.children.length) empty(dynHost, 'Dinamiche di corsa non registrate in questa corsa.');

    // split e zone
    splitBars(document.getElementById('nx-chart-splits'), splits.status === 'ok' ? splits.data.filter((p) => p.activity_id === r.id) : []);
    const zones = [r.z1, r.z2, r.z3, r.z4, r.z5];
    const zbar = box.querySelector('.nx-zones'), zleg = box.querySelector('.nx-zone-legend');
    if (zones.every((z) => z == null)) { zbar.replaceChildren(); zleg.replaceChildren(el('span', null, 'FC non disponibile.')); }
    else {
      zbar.replaceChildren(...zones.map((z, i) => { const s = el('span'); s.style.width = (z || 0) + '%'; s.style.background = ZONE_COLORS[i]; s.style.boxShadow = `0 0 8px ${ZONE_COLORS[i]}`; return s; }));
      zleg.replaceChildren(...zones.map((z, i) => {
        const s = el('span'); const sw = el('i'); sw.style.background = ZONE_COLORS[i];
        const v = markEl(el('b', null, z == null ? '—' : f0(z) + '%'), 'runs', 'z' + (i + 1), where);
        s.append(sw, `Z${i + 1} `, v); return s;
      }));
    }
  }

  // ------------------------------------------------------------ progressi corsa
  function chips(host, values, current, fmt, onPick) {
    host.replaceChildren(...values.map((v) => {
      const b = el('button', 'nx-chip', fmt(v)); b.setAttribute('aria-pressed', String(v === current));
      b.addEventListener('click', () => onPick(v)); return b;
    }));
  }

  function drawProgress() {
    const box = document.getElementById('progressi-corsa');
    if (S.page !== 'progressi') return;
    const hrp = dash.data('run_hr_pace'), hrt = dash.data('run_hr_trend'), hrs = dash.data('run_hr_summary');
    const dyn = dash.data('run_pace_dyn'), dynt = dash.data('run_dyn_trend');
    const runs = dash.data('runs'), rt = dash.data('run_trend'), wk = dash.data('run_weekly');
    if (runs.status === 'error') { failed(box.querySelector('.nx-p-hr')); return; }
    if (runs.status !== 'ok' || hrp.status !== 'ok' || dyn.status !== 'ok') return;
    const env = S.runEnv;
    box.querySelectorAll('[data-runenv]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.runenv === env)));

    // passo a parita' di FC
    const hrRows = hrp.data.filter((p) => p.env === env);
    const bins = [...new Set(hrRows.map((p) => p.hr_bin))].sort((a, b) => a - b);
    const counts = d3.rollup(hrRows, (v) => v.length, (p) => p.hr_bin);
    if (!bins.includes(S.hrBin)) S.hrBin = bins.length ? d3.greatest(bins, (b) => counts.get(b)) : null;
    chips(box.querySelector('.nx-hr-chips'), bins.filter((b) => counts.get(b) >= 2), S.hrBin, (b) => `${b} bpm`, (b) => { S.hrBin = b; drawProgress(); });
    const take = box.querySelector('.nx-hr-take');
    const sum = hrs.status === 'ok' ? hrs.data.find((q) => q.env === env && q.hr_bin === S.hrBin) : null;
    if (sum && sum.pace_now != null) {
      const key = 'key=' + encodeURIComponent(sum.key);
      const now = markEl(el('b', null, paceFmt(sum.pace_now) + '/km'), 'run_hr_summary', 'pace_now', key);
      const parts = [`A ${S.hrBin} bpm oggi corri a `, now];
      if (sum.delta_s != null) {
        const dlt = markEl(el('b', null, `${signed(sum.delta_s, f0)} s/km`), 'run_hr_summary', 'delta_s', key);
        dlt.style.color = sum.delta_s < 0 ? N.lime : sum.delta_s > 0 ? N.pink : N.muted;
        parts.push(' (media 42 gg), ', dlt, sum.delta_s < 0 ? ' rispetto a 90 giorni fa: a parità di cuore vai più veloce.' : sum.delta_s > 0 ? ' rispetto a 90 giorni fa: a parità di cuore vai più piano.' : ' rispetto a 90 giorni fa.');
      } else parts.push(' (media 42 gg). Servono più settimane di dati per il confronto a 90 giorni.');
      take.replaceChildren(...parts);
    } else take.textContent = 'Nessuna corsa continua con abbastanza minuti in questa fascia.';
    const hrSel = hrRows.filter((p) => p.hr_bin === S.hrBin);
    const trSel = hrt.status === 'ok' ? hrt.data.filter((p) => p.env === env && p.hr_bin === S.hrBin) : [];
    nxChart(box.querySelector('#nx-p-hr'), {
      xType: 'time', height: 240, yInvert: true, yFmt: paceFmt,
      series: [
        { type: 'dots', name: 'Corsa', color: N.cyan, fmt: (v) => paceFmt(v) + '/km', data: hrSel.map((p) => ({ x: parseDay(p.date), y: p.pace_s, label: `${Math.round(p.seconds / 60)} min in fascia` })) },
        { type: 'line', name: 'Media 42 gg', color: N.lime, fmt: (v) => paceFmt(v) + '/km', data: trSel.map((p) => ({ x: parseDay(p.date), y: p.pace_trend })) },
      ],
    });

    // dinamiche a parita' di passo
    const dRows = dyn.data.filter((p) => p.env === env);
    const pbins = [...new Set(dRows.map((p) => p.pace_bin))].sort((a, b) => a - b);
    const pc = d3.rollup(dRows, (v) => v.length, (p) => p.pace_bin);
    if (!pbins.includes(S.paceBin)) S.paceBin = pbins.length ? d3.greatest(pbins, (b) => pc.get(b)) : null;
    chips(box.querySelector('.nx-pace-chips'), pbins.filter((b) => pc.get(b) >= 3), S.paceBin,
      (b) => `${paceFmt(b)}–${paceFmt(b + 15)}`, (b) => { S.paceBin = b; drawProgress(); });
    const dSel = dRows.filter((p) => p.pace_bin === S.paceBin);
    const dTr = dynt.status === 'ok' ? dynt.data.filter((p) => p.env === env && p.pace_bin === S.paceBin) : [];
    const DM = [
      ['cad', 'Cadenza', 'passi/min', N.lime, f0, 'più alta = meglio'], ['gct', 'Contatto al suolo', 'ms', N.amber, f0, 'più basso = meglio'],
      ['vo', 'Oscillazione verticale', 'cm', N.violet, f1, 'più bassa = meglio'], ['vr', 'Rapporto verticale', '%', N.cyan, f1, 'più basso = meglio'],
      ['step', 'Lunghezza del passo', 'm', N.magenta, f2, 'più lunga a parità di passo = più potenza'], ['hr', 'FC', 'bpm', N.pink, f0, 'più bassa = meglio'],
    ];
    box.querySelector('.nx-pdyn').replaceChildren(...DM.filter(([k]) => dSel.some((p) => p[k] != null)).map(([k, name, unit, color, fmt, hint]) => {
      const card = el('div', 'nx-card');
      const head = el('div', 'nx-card-head'); head.append(el('h3', null, name), el('span', 'nx-note', hint));
      const ch = el('div', 'nx-chart'); card.append(head, ch);
      requestAnimationFrame(() => nxChart(ch, {
        xType: 'time', height: 130, yFmt: fmt,
        series: [
          { type: 'dots', name, color, r: 3.5, fmt: (v) => `${fmt(v)} ${unit}`, data: dSel.map((p) => ({ x: parseDay(p.date), y: p[k] })) },
          { type: 'line', name: 'Media 42 gg', color, fmt: (v) => `${fmt(v)} ${unit}`, data: dTr.map((p) => ({ x: parseDay(p.date), y: p[k + '_t'] })) },
        ],
      }));
      return card;
    }));

    // trend generali
    const rRows = runs.data.filter((p) => p.env === env);
    const tRows = rt.status === 'ok' ? rt.data.filter((p) => p.env === env) : [];
    const steady = rRows.filter((p) => p.steady && p.moving_min >= 20);
    nxChart(box.querySelector('#nx-p-ef'), {
      xType: 'time', height: 150, yFmt: f2,
      series: [
        { type: 'dots', name: 'EF', color: N.cyan, r: 3.5, fmt: f2, data: steady.filter((p) => p.ef != null).map((p) => ({ x: parseDay(p.date), y: p.ef, label: `${p.pace} @ ${f0(p.avg_hr)} bpm` })) },
        { type: 'line', name: 'Media 28 gg', color: N.cyan, fmt: f2, data: tRows.map((p) => ({ x: parseDay(p.date), y: p.ef_t })) },
      ],
    });
    nxChart(box.querySelector('#nx-p-dec'), {
      xType: 'time', height: 150, yFmt: f0, refLines: [{ y: 5, label: '5%', color: N.lime }],
      series: [
        { type: 'dots', name: 'Deriva', color: N.amber, r: 3.5, fmt: (v) => f1(v) + '%', data: steady.filter((p) => p.decoupling_pct != null).map((p) => ({ x: parseDay(p.date), y: p.decoupling_pct, label: p.name })) },
        { type: 'line', name: 'Media 28 gg', color: N.amber, fmt: (v) => f1(v) + '%', data: tRows.map((p) => ({ x: parseDay(p.date), y: p.decoupling_pct_t })) },
      ],
    });
    nxChart(box.querySelector('#nx-p-vo2'), {
      xType: 'time', height: 150, yFmt: f0,
      series: [{ type: 'line', step: true, name: 'VO2max', color: N.lime, fmt: f0, data: runs.data.filter((p) => p.vo2max != null).map((p) => ({ x: parseDay(p.date), y: p.vo2max })) }],
    });
    nxChart(box.querySelector('#nx-p-vol'), {
      xType: 'time', height: 150, yFmt: f0, zero: true,
      tipX: (v) => 'Settimana del ' + window.gx.fmtDay(new Date(v)),
      series: [{ type: 'bars', name: 'Km', color: N.violet, fmt: (v) => f1(v) + ' km', data: wk.status === 'ok' ? wk.data.map((p) => ({ x: parseDay(p.week), y: p.km, label: `${p.n} corse, ${hm(p.minutes)}` })) : [] }],
    });

    // voti per sezione
    box.querySelector('.nx-psec').replaceChildren(...SECTIONS.map(([, label, key]) => {
      const card = el('div', 'nx-card');
      const last = [...tRows].reverse().find((p) => p[key + '_t'] != null);
      const t = tier(last ? last[key + '_t'] : null);
      const v = el('span', 'nx-card-val ' + t.cls, last ? f0(last[key + '_t']) : '—');
      if (last) markEl(v, 'run_trend', key + '_t', 'id=' + last.id);
      const head = el('div', 'nx-card-head'); head.append(el('h3', null, label), v);
      const ch = el('div', 'nx-chart'); card.append(head, ch);
      requestAnimationFrame(() => nxChart(ch, {
        xType: 'time', height: 90, yDomain: [0, 100], yFmt: f0,
        series: [
          { type: 'dots', name: 'Voto', color: t.color === N.muted ? N.cyan : t.color, r: 2.5, opacity: 0.45, data: rRows.map((p) => ({ x: parseDay(p.date), y: p[key] })) },
          { type: 'line', name: 'Media 28 gg', color: t.color === N.muted ? N.cyan : t.color, data: tRows.map((p) => ({ x: parseDay(p.date), y: p[key + '_t'] })) },
        ],
      }));
      return card;
    }));
  }

  window.nx = { N, MONO, nxChart, ring, tier, el, markEl, empty, failed, chips, paceFmt };

  // ------------------------------------------------------------ wiring
  document.querySelectorAll('[data-runenv]').forEach((b) => b.addEventListener('click', () => { S.runEnv = b.dataset.runenv; drawProgress(); }));
  const drawAll = () => { drawRunReport(); drawProgress(); };
  const base = window.gxDraw;
  window.gxDraw = () => { base(); drawAll(); };
  dash.onData(drawAll);
})();
