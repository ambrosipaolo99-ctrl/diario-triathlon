// ============================================================== Obiettivo: calcoli derivati
dash.calc('goal_weeks', {
  inputs: ['goal_plan', 'goal_grades'],
  title: 'Piano: km previsti e svolti per settimana',
  description: 'Per settimana del piano: km previsti (gara esclusa), km corsi in quei giorni, sedute svolte e voto medio delle corse abbinate al piano.',
  fn: (goal_plan, goal_grades) => {
    const weeks = {};
    goal_plan.forEach((p) => {
      const w = (weeks[p.week] ||= { week: p.week, phase: p.phase, planned_km: 0, done_km: 0, sessions: 0, done: 0, grades: [] });
      if (p.type !== 'gara' && p.km) w.planned_km += p.km;
      if (p.type !== 'riposo' && p.type !== 'gara') w.sessions += 1;
      if (p.status && p.status.startsWith('svolto')) w.done += 1;
    });
    goal_grades.forEach((g) => {
      const d = new Date(g.date + 'T00:00:00Z');
      d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
      const w = weeks[d.toISOString().slice(0, 10)];
      if (!w) return;
      w.done_km += g.km || 0;
      if (g.type_source === 'piano' && g.score != null) w.grades.push(g.score);
    });
    return Object.values(weeks).map((w) => ({
      week: w.week, phase: w.phase, planned_km: Math.round(w.planned_km * 10) / 10, done_km: Math.round(w.done_km * 10) / 10,
      sessions: w.sessions, done: w.done, avg_grade: w.grades.length ? Math.round(w.grades.reduce((s, x) => s + x, 0) / w.grades.length) : null,
    })).sort((a, b) => a.week.localeCompare(b.week));
  },
});
dash.calc('race_delta', {
  inputs: ['race_estimate'],
  title: 'Stima gara: variazione',
  description: 'Ultima stima centrale e differenza in secondi rispetto a 7 giorni prima e alla prima stima del blocco (negativo = più veloce).',
  fn: (race_estimate) => {
    if (!race_estimate.length) return [];
    const rows = [...race_estimate].sort((a, b) => a.date.localeCompare(b.date));
    const last = rows[rows.length - 1];
    const t7 = Date.parse(last.date) - 7 * 864e5;
    const prev = rows.filter((r) => Date.parse(r.date) <= t7).pop() || null;
    return [{ date: last.date, central_s: last.central_s,
      delta_7d_s: prev ? Math.round(last.central_s - prev.central_s) : null,
      delta_start_s: Math.round(last.central_s - rows[0].central_s), first_date: rows[0].date }];
  },
});

// ============================================================== Obiettivo: disegno neon
(() => {
  const { N, nxChart, ring, tier, el, markEl, empty, failed } = window.nx;
  const { loc, parseDay } = window.gx;
  const S = window.gxState;
  Object.assign(S, { goalSel: null });
  const f0 = d3.format('.0f'), f1 = d3.format('.1f');
  const fmtDow = loc.utcFormat('%a %-d');
  const fmtDay = loc.utcFormat('%-d %b');
  const fmtDayY = loc.utcFormat('%-d %B %Y');
  const hms = (s) => { if (s == null) return '—'; const t = Math.round(s); return `${Math.floor(t / 3600)}:${String(Math.floor(t % 3600 / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };
  const hmAxis = (m) => `${Math.floor(m / 60)}:${String(Math.round(m % 60)).padStart(2, '0')}`;
  const signedTime = (s) => { if (s == null) return '—'; const a = Math.abs(Math.round(s)); return (s < 0 ? '−' : s > 0 ? '+' : '±') + `${Math.floor(a / 60)}:${String(a % 60).padStart(2, '0')}`; };
  const TYPE = {
    facile: { label: 'Facile', color: N.cyan }, 'qualità': { label: 'Qualità', color: N.magenta },
    lungo: { label: 'Lungo', color: N.lime }, gara: { label: 'Gara', color: N.amber }, riposo: { label: 'Riposo', color: N.muted },
  };
  const STATUS = {
    svolto: N.lime, 'svolto (spostato)': N.lime, 'svolto (anticipato)': N.lime, 'svolto (altro tipo)': N.amber,
    sostituito: N.amber, 'corsa extra': N.violet, saltato: N.pink, oggi: N.cyan, 'da fare': N.muted, riposo: N.muted,
  };
  const EVID = { CONSOLIDATO: N.lime, EMERGENTE: N.cyan, 'PRELIMINARE MA RILEVANTE': N.amber };
  const mk = (tag, cls, text, src, field, where) => markEl(el(tag, cls, text), src, field, where);
  // le etichette [CONSOLIDATO] nei testi diventano chip colorate (testo dei dati, mai markup)
  const evidText = (host, text) => {
    host.replaceChildren();
    String(text || '').split(/(\[(?:CONSOLIDATO|EMERGENTE|PRELIMINARE MA RILEVANTE)\])/).forEach((part) => {
      const m = part.match(/^\[(.+)\]$/);
      if (m) { const c = el('span', 'gl-ev', m[1]); c.style.color = EVID[m[1]]; host.append(c); } else if (part) host.append(part);
    });
    return host;
  };

  function activeGoal(g) {
    return g.status === 'ok' ? g.data.find((r) => r.status === 'attivo') || null : null;
  }

  // ------------------------------------------------------------ card nella pagina Oggi
  function drawTodayCard() {
    const card = document.getElementById('obiettivo-oggi');
    const g = dash.data('goals'), e = dash.data('race_estimate'), p = dash.data('goal_plan');
    if (g.status === 'error') { failed(card.querySelector('.gl-today-body')); return; }
    const goal = activeGoal(g);
    card.hidden = !goal && g.status === 'ok';
    if (!goal) return;
    const body = card.querySelector('.gl-today-body');
    const head = el('div', 'gl-today-head');
    head.append(mk('b', 'gl-today-name', goal.name, 'goals', 'name', 'id=' + goal.id), ' · tra ',
      mk('b', null, String(goal.days_to), 'goals', 'days_to', 'id=' + goal.id), ' giorni');
    const parts = [head];
    if (e.status === 'ok' && e.data.length) {
      const last = e.data[e.data.length - 1];
      const line = el('div', 'gl-today-est');
      line.append('Stima ', mk('b', 'gl-mono', last.central_fmt, 'race_estimate', 'central_fmt', 'date=' + last.date),
        ' (', mk('span', null, last.low_fmt, 'race_estimate', 'low_fmt', 'date=' + last.date), '–',
        mk('span', null, last.high_fmt, 'race_estimate', 'high_fmt', 'date=' + last.date), ') · ',
        mk('span', 'gl-mono', last.pace_fmt, 'race_estimate', 'pace_fmt', 'date=' + last.date), '/km');
      parts.push(line);
    }
    if (p.status === 'ok') {
      const t = p.data.find((r) => r.status === 'oggi');
      if (t) {
        const w = el('div', 'gl-today-wk');
        const chip = el('span', 'gl-type', TYPE[t.type]?.label || t.type); chip.style.color = TYPE[t.type]?.color;
        w.append('Oggi: ', chip, ' ', mk('b', null, t.title, 'goal_plan', 'title', 'date=' + t.date));
        if (t.pace_fmt) w.append(' · ', mk('span', 'gl-mono', t.pace_fmt, 'goal_plan', 'pace_fmt', 'date=' + t.date), '/km');
        if (t.hr_fmt) w.append(' · FC ', mk('span', 'gl-mono', t.hr_fmt, 'goal_plan', 'hr_fmt', 'date=' + t.date));
        parts.push(w);
      }
    }
    const go = el('button', 'gx-chip', 'Apri obiettivo →'); go.addEventListener('click', () => window.gxShow('obiettivo'));
    parts.push(go);
    body.replaceChildren(...parts);
  }

  // ------------------------------------------------------------ pagina Obiettivo
  function drawHead(root, goal) {
    const where = 'id=' + goal.id;
    root.querySelector('.gl-name').replaceChildren(mk('span', null, goal.name, 'goals', 'name', where));
    const meta = root.querySelector('.gl-meta');
    meta.replaceChildren(mk('span', null, fmtDayY(parseDay(goal.date)), 'goals', 'date', where), ' · ',
      mk('span', null, goal.discipline, 'goals', 'discipline', where), ' · ',
      mk('span', null, goal.distance, 'goals', 'distance', where), ' · priorità ',
      mk('b', null, goal.priority, 'goals', 'priority', where));
    root.querySelector('.gl-days').replaceChildren(mk('span', null, String(goal.days_to), 'goals', 'days_to', where));
  }

  function drawEstimate(root, goal) {
    const e = dash.data('race_estimate'), m = dash.data('race_methods'), f = dash.data('race_factors'), dl = dash.data('race_delta');
    const box = root.querySelector('#goal-estimate');
    if (e.status === 'error') { failed(box); return; }
    if (e.status !== 'ok') return;
    if (!e.data.length) { empty(box, goal.discipline === 'corsa' ? 'Stima non ancora disponibile.' : 'Stima, piano e voti sono disponibili per gli obiettivi di corsa.'); return; }
    const last = e.data[e.data.length - 1];
    const where = 'date=' + last.date;
    const time = box.querySelector('.gl-time');
    time.replaceChildren(mk('span', null, last.central_fmt, 'race_estimate', 'central_fmt', where));
    box.querySelector('.gl-range').replaceChildren(mk('span', null, last.low_fmt, 'race_estimate', 'low_fmt', where), ' – ',
      mk('span', null, last.high_fmt, 'race_estimate', 'high_fmt', where));
    box.querySelector('.gl-pace').replaceChildren('passo ', mk('b', null, last.pace_fmt, 'race_estimate', 'pace_fmt', where),
      '/km · aggiornata al ', fmtDay(parseDay(last.date)));
    const delta = box.querySelector('.gl-delta');
    const d = dl.status === 'ok' && dl.data[0];
    delta.replaceChildren();
    if (d && d.delta_7d_s != null) {
      const c = mk('span', 'nx-chip-delta', signedTime(d.delta_7d_s), 'race_delta', 'delta_7d_s', 'date=' + d.date);
      c.style.color = d.delta_7d_s <= 0 ? N.lime : N.amber;
      delta.append(c, ' in 7 giorni');
    }
    const rg = box.querySelector('.gl-conf-ring');
    rg.querySelector('svg')?.remove();
    ring(rg, last.confidence, 112, 9);
    rg.prepend(rg.lastChild);
    rg.querySelector('b').replaceChildren(mk('span', null, String(last.confidence), 'race_estimate', 'confidence', where));
    box.querySelector('.gl-conf-label').replaceChildren('Affidabilità ', mk('b', null, last.confidence_label, 'race_estimate', 'confidence_label', where));
    const fl = box.querySelector('.gl-factors');
    if (f.status === 'ok') {
      fl.replaceChildren(...f.data.map((r) => {
        const li = el('li');
        li.append(mk('span', 'gl-impact', String(r.impact), 'race_factors', 'impact', 'key=' + r.key), ' ',
          mk('span', null, r.text, 'race_factors', 'text', 'key=' + r.key));
        return li;
      }));
    }
    const mh = root.querySelector('.gl-methods');
    if (m.status === 'error') failed(mh);
    else if (m.status === 'ok') {
      mh.replaceChildren(...m.data.map((r) => {
        const c = el('div', 'nx-card gl-method' + (r.outlier ? ' gl-outlier' : ''));
        const w = 'key=' + r.key;
        const head = el('div', 'nx-card-head');
        const ev = el('span', 'gl-ev', r.evidence); ev.style.color = EVID[r.evidence];
        head.append(mk('h3', null, r.name, 'race_methods', 'name', w), ev);
        const big = el('div', 'gl-method-time');
        big.append(mk('b', null, r.time_fmt, 'race_methods', 'time_fmt', w), ' ',
          mk('span', 'nx-note', r.pace_fmt, 'race_methods', 'pace_fmt', w), el('span', 'nx-note', '/km'));
        const wt = el('div', 'gl-weight');
        const bar = el('div', 'gl-bar'); const fill = el('span'); fill.style.width = Math.min(100, r.weight_pct) + '%'; bar.append(fill);
        wt.append(el('span', 'nx-note', 'peso '), mk('b', null, f0(r.weight_pct), 'race_methods', 'weight_pct', w), el('span', 'nx-note', '% · affidabilità '),
          mk('b', null, f0(r.reliability_pct), 'race_methods', 'reliability_pct', w), el('span', 'nx-note', '%' + (r.outlier ? ' · lontano dagli altri' : '')));
        c.append(head, big, bar, wt, mk('p', 'nx-sec-note', r.detail, 'race_methods', 'detail', w));
        return c;
      }));
    }
    // grafico della stima giorno per giorno
    const ch = root.querySelector('#gl-est-chart');
    const pts = e.data.map((r) => ({ ...r, _d: parseDay(r.date) }));
    const M = { cs_s: ['Velocità critica', N.violet], vdot_s: ['VDOT', N.magenta], riegel_s: ['Riegel', N.amber], durability_s: ['Durability', N.lime] };
    nxChart(ch, {
      xType: 'time', height: 240, yInvert: true, yFmt: hmAxis,
      series: [
        { type: 'band', color: N.cyan, opacity: 0.14, data: pts.map((r) => ({ x: r._d, y: r.low_s / 60, y2: r.high_s / 60 })) },
        ...Object.entries(M).map(([k, [name, color]]) => ({ type: 'dots', name, color, r: 2.5, opacity: 0.55, fmt: (v) => hms(v * 60), data: pts.map((r) => ({ x: r._d, y: r[k] != null ? r[k] / 60 : null })) })),
        { type: 'line', name: 'Stima centrale', color: N.cyan, width: 2.5, fmt: (v) => hms(v * 60), data: pts.map((r) => ({ x: r._d, y: r.central_s / 60, label: `${r.low_fmt}–${r.high_fmt}, affidabilità ${r.confidence}` })) },
      ],
    });
    const lg = root.querySelector('.gl-est-legend');
    lg.replaceChildren(...[['Stima centrale', N.cyan], ...Object.values(M)].map(([n, c]) => { const s = el('span'); const i = el('i'); i.style.background = c; s.append(i, n); return s; }),
      (() => { const s = el('span'); const i = el('i'); i.style.background = N.cyan; i.style.opacity = 0.3; s.append(i, 'forchetta'); return s; })());
  }

  function drawPlan(root) {
    const p = dash.data('goal_plan'), wk = dash.data('goal_weeks');
    const host = root.querySelector('.gl-plan');
    if (p.status === 'error') { failed(host); return; }
    if (p.status !== 'ok') return;
    if (!p.data.length) { empty(host, 'Nessun piano per questo obiettivo.'); return; }
    const weeks = d3.groups(p.data, (r) => r.week);
    // riepilogo degli adattamenti: cosa e' cambiato rispetto al piano di partenza e perche'
    const changed = p.data.filter((r) => (r.adapted || r.warning || r.done_note) && (r.status === 'oggi' || r.status === 'da fare'
      || r.week === weeks.find(([, ds]) => ds.some((x) => x.status === 'oggi' || x.status === 'da fare'))?.[0]));
    const sumCard = el('div', 'nx-card gl-changes');
    const sh = el('div', 'nx-card-head'); sh.append(el('h3', null, 'Come si è adattato il piano'), el('span', 'nx-note', 'in base a quanto hai svolto, al volume e al recupero'));
    sumCard.append(sh);
    if (!changed.length) sumCard.append(el('p', 'nx-note', 'Nessuna modifica: stai seguendo il piano.'));
    else {
      const ul = el('ul', 'gl-change-list');
      changed.forEach((r) => {
        const where = 'date=' + r.date;
        const li = el('li');
        li.append(el('b', 'gl-mono', fmtDow(parseDay(r.date))), ' ', mk('span', null, r.title, 'goal_plan', 'title', where), ': ');
        [['done_note', 'gl-done'], ['adapted', 'gl-adapt-note'], ['warning', 'gl-warn-note']].forEach(([f, c]) => {
          if (r[f]) li.append(mk('span', c, r[f], 'goal_plan', f, where), ' ');
        });
        ul.append(li);
      });
      sumCard.append(ul);
    }
    host.replaceChildren(timeline(p.data), sumCard, ...weeks.map(([week, days]) => {
      const card = el('div', 'nx-card gl-week');
      const head = el('div', 'nx-card-head');
      const end = new Date(parseDay(week).getTime() + 6 * 864e5);
      const title = el('h3'); title.append(mk('span', null, days[0].phase, 'goal_plan', 'phase', 'date=' + days[0].date), ` · ${fmtDay(parseDay(week))} – ${fmtDay(end)}`);
      const w = wk.status === 'ok' ? wk.data.find((r) => r.week === week) : null;
      const sum = el('span', 'nx-note');
      if (w) {
        sum.append(mk('b', 'gl-mono', f1(w.done_km), 'goal_weeks', 'done_km', 'week=' + week), ' / ',
          mk('b', 'gl-mono', f1(w.planned_km), 'goal_weeks', 'planned_km', 'week=' + week), ' km · ',
          mk('b', 'gl-mono', String(w.done), 'goal_weeks', 'done', 'week=' + week), '/',
          mk('b', 'gl-mono', String(w.sessions), 'goal_weeks', 'sessions', 'week=' + week), ' sedute');
        if (w.avg_grade != null) {
          const t = tier(w.avg_grade);
          sum.append(' · voto medio ', mk('b', 'gl-mono ' + t.cls, String(w.avg_grade), 'goal_weeks', 'avg_grade', 'week=' + week));
        }
      }
      head.append(title, sum);
      card.append(head, ...days.map(dayRow));
      return card;
    }));
  }

  // timeline verticale dei prossimi giorni: cosa cambia, rispetto a cosa, e perche'
  function timeline(plan) {
    const card = el('div', 'nx-card rt-card');
    const tp = dash.data('taper_plan');
    const head = el('div', 'nx-card-head');
    head.append(el('h3', null, 'Road to Race'), el('span', 'nx-note', 'prossimi 14 giorni · si ricalcola a ogni sincronizzazione'));
    card.append(head);
    const now = Date.now();
    const next = plan.filter((r) => r.status === 'oggi' || r.status === 'da fare').slice(0, 14);
    const fresh = next.filter((r) => r.changed_on && now - Date.parse(r.changed_on) <= 2 * 864e5);
    if (fresh.length) {
      const b = el('div', 'rt-banner');
      b.append(el('b', null, `↻ Il piano è cambiato: ${fresh.length} giorn${fresh.length === 1 ? 'o' : 'i'} `),
        `in risposta agli ultimi allenamenti (${fmtDay(parseDay(fresh[0].changed_on))}).`);
      card.append(b);
    }
    if (tp.status === 'ok' && tp.data.length) {
      const blocks = el('div', 'rt-taper');
      tp.data.slice().reverse().forEach((b) => {
        const w = 'block=' + b.block;
        const x = el('div', 'rt-block');
        const on = now >= Date.parse(b.start) && now <= Date.parse(b.end) + 864e5;
        if (on) x.classList.add('rt-block-on');
        x.append(mk('span', 'rt-block-name', b.block, 'taper_plan', 'block', w),
          mk('b', 'gl-mono', `−${b.reduction_pct}%`, 'taper_plan', 'reduction_pct', w),
          el('span', 'nx-note', `${f1(b.planned_km)} / ${f1(b.target_km)} km`));
        blocks.append(x);
      });
      card.append(blocks, evidText(el('p', 'nx-note'), `Scarico esponenziale: volume ridotto fino al −${tp.data[0].final_cut_pct}% il giorno prima della gara, intensità e frequenza mantenute (Bosquet 2007) [CONSOLIDATO].`));
    }
    const list = el('ol', 'rt-list');
    next.forEach((r) => {
      const where = 'date=' + r.date;
      const ty = TYPE[r.type] || { label: r.type, color: N.muted };
      const li = el('li', 'rt-item' + (r.changed_from ? ' rt-changed' : '') + (r.status === 'oggi' ? ' rt-today' : ''));
      li.style.setProperty('--rt', ty.color);
      const when = el('div', 'rt-when');
      when.append(el('b', null, r.status === 'oggi' ? 'Oggi' : fmtDow(parseDay(r.date))), el('span', 'nx-note', r.d === 0 ? 'gara' : `−${r.d} gg`));
      const what = el('div', 'rt-what');
      const top = el('div', 'rt-title');
      const chip = mk('span', 'gl-type', ty.label, 'goal_plan', 'type', where); chip.style.color = ty.color;
      top.append(chip, mk('b', null, r.title, 'goal_plan', 'title', where));
      if (r.km) top.append(el('span', 'nx-note', ` · ${f1(r.km)} km`));
      if (r.changed_on && now - Date.parse(r.changed_on) <= 2 * 864e5) top.append(el('span', 'rt-new', 'nuovo'));
      what.append(top);
      if (r.changed_from) {
        const ch = el('div', 'rt-diff');
        ch.append(el('span', 'nx-note', 'prima: '), mk('s', null, r.changed_from, 'goal_plan', 'changed_from', where));
        what.append(ch);
      }
      if (r.adapted) what.append(mk('p', 'rt-why', '↻ ' + r.adapted, 'goal_plan', 'adapted', where));
      if (r.warning) what.append(mk('p', 'gl-warn-note', '⚠ ' + r.warning, 'goal_plan', 'warning', where));
      li.append(when, what);
      list.append(li);
    });
    card.append(list);
    return card;
  }

  function dayRow(r) {
    const where = 'date=' + r.date;
    const det = el('details', 'gl-day' + (r.status === 'oggi' ? ' gl-today' : '') + (r.type === 'riposo' ? ' gl-rest' : ''));
    if (r.status === 'oggi') det.open = true;
    const sm = el('summary');
    const ty = TYPE[r.type] || { label: r.type, color: N.muted };
    const chip = mk('span', 'gl-type', ty.label, 'goal_plan', 'type', where); chip.style.color = ty.color;
    // riga 2: il previsto (km, minuti, passo e FC target) · riga 3: lo svolto, in verde
    const plan = el('span', 'gl-plan-line');
    const parts = [];
    if (r.km) {
      const a = el('span'); a.append(mk('b', null, f1(r.km), 'goal_plan', 'km', where), ' km · ', mk('span', null, String(r.minutes), 'goal_plan', 'minutes', where), "'");
      parts.push(a);
    }
    if (r.pace_fmt) { const a = el('span'); a.append(mk('span', null, r.pace_fmt, 'goal_plan', 'pace_fmt', where), '/km'); parts.push(a); }
    if (r.hr_fmt) { const a = el('span'); a.append('FC ', mk('span', null, r.hr_fmt, 'goal_plan', 'hr_fmt', where)); parts.push(a); }
    if (parts.length) {
      if (r.done_km != null) plan.append(el('span', 'gl-lbl', 'Previsti'));
      parts.forEach((x, i) => { if (i) plan.append(el('span', 'gl-sep', '·')); plan.append(x); });
    }
    const done = el('span', 'gl-done-line');
    if (r.done_km != null) {
      done.append(el('span', 'gl-lbl', 'Svolti'), mk('b', null, f1(r.done_km), 'goal_plan', 'done_km', where), ' km');
      if (r.done_pace_fmt) done.append(el('span', 'gl-sep', '·'), mk('b', null, r.done_pace_fmt, 'goal_plan', 'done_pace_fmt', where), '/km');
    }
    const st = el('span', 'gl-status');
    const sc = mk('span', null, r.status, 'goal_plan', 'status', where); sc.style.color = STATUS[r.status] || N.muted;
    st.append(sc);
    if (r.grade != null) { const t = tier(r.grade); st.append(' · ', mk('b', t.cls, String(r.grade), 'goal_plan', 'grade', where)); }
    if (r.adapted) st.append(el('span', 'gl-adapted', ' ↻'));
    if (r.warning) { st.append(el('span', 'gl-warn-note', ' ⚠')); det.open = true; }
    sm.append(el('span', 'gl-dow', fmtDow(parseDay(r.date))), chip, mk('span', 'gl-title', r.title, 'goal_plan', 'title', where), st);
    if (plan.childNodes.length) sm.append(plan);
    if (done.childNodes.length) sm.append(done);
    const body = el('div', 'gl-day-body');
    if (r.done_note) body.append(mk('p', 'gl-adapt-note', r.done_note, 'goal_plan', 'done_note', where));
    if (r.adapted) body.append(mk('p', 'gl-adapt-note', r.adapted, 'goal_plan', 'adapted', where));
    if (r.warning) body.append(mk('p', 'gl-warn-note', r.warning, 'goal_plan', 'warning', where));
    if (r.structure) { const p = el('p'); p.append(el('b', null, 'Come: '), mk('span', null, r.structure, 'goal_plan', 'structure', where)); body.append(p); }
    if (r.purpose) { const p = el('p'); p.append(el('b', null, 'Obiettivo fisiologico: ')); const s = mk('span', null, '', 'goal_plan', 'purpose', where); evidText(s, r.purpose); p.append(s); body.append(p); }
    if (r.notes) { const p = el('p'); p.append(el('b', null, r.type === 'gara' || r.d <= 6 ? 'Gara e alimentazione: ' : 'Alimentazione e recupero: ')); const s = mk('span', null, '', 'goal_plan', 'notes', where); evidText(s, r.notes); p.append(s); body.append(p); }
    if (r.activity_id && r.grade != null) {
      const b = el('button', 'gx-chip', 'Vedi il voto →');
      b.addEventListener('click', (ev) => { ev.preventDefault(); S.goalSel = r.activity_id; drawGrades(document.getElementById('obiettivo')); document.getElementById('gl-grade-detail').scrollIntoView({ block: 'nearest' }); });
      body.append(b);
    }
    if (r.generated_on) body.append(el('p', 'nx-note', `Proposto il ${fmtDay(parseDay(r.generated_on))}` + (r.status === 'da fare' || r.status === 'oggi' ? ' · si aggiorna dopo ogni allenamento' : '')));
    det.append(sm, body);
    return det;
  }

  function drawZones(root) {
    const z = dash.data('goal_zones');
    const tb = root.querySelector('.gl-zones tbody');
    if (z.status === 'error') { failed(tb.closest('.gl-tablebox')); return; }
    if (z.status !== 'ok') return;
    tb.replaceChildren(...z.data.map((r) => {
      const tr = el('tr'); tr.dataset.key = r.key;
      [[r.name, ''], [r.pace_fmt, 'num'], [r.hr_fmt, 'num'], [r.use, 'wrap']].forEach(([t, c]) => tr.append(el('td', c, t)));
      return tr;
    }));
  }

  function drawGrades(root) {
    const g = dash.data('goal_grades'), parts = dash.data('goal_grade_parts');
    const tb = root.querySelector('.gl-grades tbody');
    if (g.status === 'error') { failed(tb.closest('.gl-tablebox')); return; }
    if (g.status !== 'ok') return;
    const rows = [...g.data].sort((a, b) => b.date.localeCompare(a.date) || b.km - a.km);
    if (!S.goalSel || !rows.some((r) => r.id === S.goalSel)) S.goalSel = rows[0]?.id || null;
    tb.replaceChildren(...rows.map((r) => {
      const tr = el('tr'); tr.dataset.key = r.id; tr.tabIndex = 0;
      if (r.id === S.goalSel) tr.classList.add('sel');
      const t = tier(r.score);
      [[fmtDay(parseDay(r.date)), ''], [r.name || '', 'wrap'], [TYPE[r.type]?.label || r.type, ''], [r.type_source, 'gx-hide-narrow'],
        [f1(r.km), 'num gx-hide-narrow'], [r.pace_fmt, 'num'], [r.score == null ? '—' : String(r.score), 'num ' + t.cls]]
        .forEach(([x, c]) => tr.append(el('td', c, x)));
      return tr;
    }));
    const det = root.querySelector('#gl-grade-detail');
    const r = rows.find((q) => q.id === S.goalSel);
    if (!r) { det.hidden = true; return; }
    det.hidden = false;
    const w = 'id=' + r.id;
    const rg = det.querySelector('.gl-grade-ring');
    rg.querySelector('svg')?.remove();
    const t = ring(rg, r.score, 112, 9);
    rg.prepend(rg.lastChild);
    rg.querySelector('b').replaceChildren(mk('span', t.cls, r.score == null ? '—' : String(r.score), 'goal_grades', 'score', w));
    det.querySelector('.gl-grade-title').replaceChildren(mk('span', null, r.name, 'goal_grades', 'name', w));
    const ty = TYPE[r.type] || { label: r.type, color: N.muted };
    const chip = mk('span', 'gl-type', ty.label, 'goal_grades', 'type', w); chip.style.color = ty.color;
    det.querySelector('.gl-grade-meta').replaceChildren(fmtDayY(parseDay(r.date)), ' · ', chip, ' · ',
      r.type_source === 'piano' ? 'abbinata al piano: ' : 'tipo dedotto dalla corsa (nessun piano quel giorno)',
      r.plan_title ? mk('b', null, r.plan_title, 'goal_grades', 'plan_title', w) : '',
      ' · ', mk('span', 'gl-mono', f1(r.km), 'goal_grades', 'km', w), ' km a ', mk('span', 'gl-mono', r.pace_fmt, 'goal_grades', 'pace_fmt', w), '/km',
      r.avg_hr ? ' · FC ' : '', r.avg_hr ? mk('span', 'gl-mono', f0(r.avg_hr), 'goal_grades', 'avg_hr', w) : '');
    det.querySelector('.gl-grade-comment').replaceChildren(mk('span', null, r.comment, 'goal_grades', 'comment', w));
    const host = det.querySelector('.gl-parts');
    if (parts.status === 'error') { failed(host); return; }
    const comps = parts.status === 'ok' ? parts.data.filter((q) => q.activity_id === r.id) : [];
    host.replaceChildren(...comps.map((q) => {
      const row = el('div', 'gl-part' + (q.score == null ? ' gl-na' : ''));
      const k = 'key=' + q.key;
      const tt = tier(q.score);
      const name = el('div', 'gl-part-name');
      name.append(mk('b', null, q.component, 'goal_grade_parts', 'component', k), ' ',
        el('span', 'nx-note', 'peso '), mk('span', 'nx-note', String(q.eff_weight), 'goal_grade_parts', 'eff_weight', k), el('span', 'nx-note', '%'));
      const bar = el('div', 'gl-bar'); const fill = el('span'); fill.style.width = (q.score ?? 0) + '%'; fill.style.background = tt.color; fill.style.color = tt.color; bar.append(fill);
      const val = el('div', 'gl-part-val');
      val.append(mk('b', 'gl-mono ' + tt.cls, q.score == null ? 'n/d' : String(q.score), 'goal_grade_parts', 'score', k), ' · ',
        mk('span', 'gl-mono', q.value, 'goal_grade_parts', 'value', k));
      row.append(name, val, bar, mk('p', 'nx-sec-note', q.note, 'goal_grade_parts', 'note', k));
      return row;
    }));
  }

  function drawHistory(root) {
    const g = dash.data('goals');
    const host = root.querySelector('.gl-history');
    if (g.status === 'error') { failed(host); return; }
    if (g.status !== 'ok') return;
    host.replaceChildren(...[...g.data].sort((a, b) => b.date.localeCompare(a.date)).map((r) => {
      const w = 'id=' + r.id;
      const c = el('div', 'gl-goal gl-g-' + r.status);
      const top = el('div', 'gl-goal-top');
      const st = mk('span', 'gl-type', r.status, 'goals', 'status', w);
      st.style.color = r.status === 'attivo' ? N.cyan : r.status === 'futuro' ? N.violet : N.muted;
      top.append(st, mk('span', 'gl-prio', r.priority, 'goals', 'priority', w));
      const meta = el('div', 'nx-note');
      meta.append(mk('span', null, fmtDayY(parseDay(r.date)), 'goals', 'date', w), ' · ', mk('span', null, r.discipline, 'goals', 'discipline', w),
        ' · ', mk('span', null, r.distance, 'goals', 'distance', w));
      const res = el('div', 'gl-goal-res');
      if (r.result_fmt) res.append('Tempo ', mk('b', 'gl-mono', r.result_fmt, 'goals', 'result_fmt', w), r.result_date && r.result_date !== r.date ? ` (attività del ${fmtDay(parseDay(r.result_date))})` : '');
      else if (r.status === 'attivo') res.append('tra ', mk('b', 'gl-mono', String(r.days_to), 'goals', 'days_to', w), ' giorni');
      c.append(top, mk('b', 'gl-goal-name', r.name, 'goals', 'name', w), meta, res);
      return c;
    }));
  }

  function drawGoal() {
    drawTodayCard();
    if (S.page !== 'obiettivo') return;
    const root = document.getElementById('obiettivo');
    const g = dash.data('goals');
    if (g.status === 'error') { failed(root.querySelector('#goal-head')); return; }
    const goal = activeGoal(g);
    if (!goal) { if (g.status === 'ok') empty(root.querySelector('#goal-head'), 'Nessun obiettivo attivo: aggiungine uno con "python main.py goal add".'); drawHistory(root); return; }
    drawHead(root, goal);
    drawEstimate(root, goal);
    drawPlan(root);
    drawZones(root);
    drawGrades(root);
    drawHistory(root);
  }

  // ------------------------------------------------------------ wiring
  const tb = document.querySelector('.gl-grades tbody');
  const pick = (ev) => {
    const tr = ev.target.closest('tr[data-key]');
    if (!tr) return;
    S.goalSel = tr.dataset.key;
    drawGrades(document.getElementById('obiettivo'));
    document.getElementById('gl-grade-detail').scrollIntoView({ block: 'nearest' });
  };
  tb.addEventListener('click', pick);
  tb.addEventListener('keydown', (ev) => { if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); pick(ev); } });
  const base = window.gxDraw;
  window.gxDraw = () => { base(); drawGoal(); };
  dash.onData(drawGoal);
})();
