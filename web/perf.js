// ============================================================== Analisi predittive per la corsa
// Prontezza ANS x CNS (Oggi), carico cuore vs struttura, carburante, deriva biomeccanica (report corsa) e
// modello di scarico (Obiettivo). Il test neuromuscolare si salva solo sul dispositivo (window.dtLocal,
// presente nella web app); su claude.ai la matrice usa solo il sistema autonomo.
(() => {
  const { N, nxChart, ring, tier, el, markEl, empty, failed } = window.nx;
  const { loc, parseDay } = window.gx;
  const S = window.gxState;
  const f0 = d3.format('.0f'), f1 = d3.format('.1f');
  const fmtDay = loc.utcFormat('%-d %b');
  const EVID = { CONSOLIDATO: N.lime, EMERGENTE: N.cyan, 'PRELIMINARE MA RILEVANTE': N.amber };
  const mk = (tag, cls, text, src, field, where) => markEl(el(tag, cls, text), src, field, where);
  const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  const evid = (host, text) => {
    String(text || '').split(/(\[(?:CONSOLIDATO|EMERGENTE|PRELIMINARE MA RILEVANTE)\])/).forEach((part) => {
      const m = part.match(/^\[(.+)\]$/);
      if (m) { const c = el('span', 'gl-ev', m[1]); c.style.color = EVID[m[1]]; host.append(c); } else if (part) host.append(part);
    });
    return host;
  };
  const head = (title, note) => { const h = el('div', 'nx-card-head'); h.append(el('h3', null, title)); if (note) h.append(el('span', 'nx-note', note)); return h; };
  const bar = (v, color) => { const b = el('div', 'gl-bar'); const s = el('span'); s.style.width = Math.max(0, Math.min(100, v ?? 0)) + '%'; s.style.background = color; s.style.color = color; b.append(s); return b; };

  // ------------------------------------------------------------ test neuromuscolare (solo sul dispositivo)
  const CNS_KEY = 'cns-tests';
  let cnsTests = null;           // [{date, kind: 'tap'|'cmj', value}]
  const local = window.dtLocal;
  if (local) local.get(CNS_KEY).then((v) => { cnsTests = Array.isArray(v) ? v : []; draw(); });

  function cnsState(kind) {
    const t = today();
    const all = (cnsTests || []).filter((x) => x.kind === kind);
    const now = all.find((x) => x.date === t);
    const base = all.filter((x) => x.date < t && (Date.parse(t) - Date.parse(x.date)) / 864e5 <= 28).map((x) => x.value);
    if (!now) return { kind, value: null, n: base.length };
    if (base.length < 5) return { kind, value: now.value, n: base.length, state: null };
    const mean = d3.mean(base), sd = d3.deviation(base) || 0;
    const limit = mean - Math.max(0.5 * sd, 0.03 * mean);
    return { kind, value: now.value, n: base.length, mean, state: now.value < limit ? 'basso' : 'alto' };
  }

  async function saveCns(kind, value) {
    const t = today();
    const list = (cnsTests || []).filter((x) => !(x.kind === kind && x.date === t));
    const prev = (cnsTests || []).find((x) => x.kind === kind && x.date === t);
    list.push({ date: t, kind, value: prev ? Math.max(prev.value, value) : value });     // il migliore del giorno
    cnsTests = list.filter((x) => (Date.parse(t) - Date.parse(x.date)) / 864e5 <= 120);
    await local.set(CNS_KEY, cnsTests);
    draw();
  }

  function tappingTest() {
    const ov = el('div', 'px-tap');
    const msg = el('p', 'px-tap-msg', "Tocca il riquadro il più velocemente possibile con l'indice della mano dominante, per 10 secondi.");
    const pad = el('button', 'px-tap-pad', 'Inizia');
    const close = el('button', 'app-btn', 'Annulla');
    ov.append(msg, pad, close);
    document.body.append(ov);
    let taps = 0, phase = 'idle', timer = null;
    close.addEventListener('click', () => { clearInterval(timer); ov.remove(); });
    pad.addEventListener('pointerdown', (ev) => {
      ev.preventDefault();
      if (!ev.isPrimary) return;                 // un dito solo: niente tocchi multipli
      if (phase === 'idle') {
        phase = 'count'; let n = 3; pad.textContent = String(n);
        timer = setInterval(() => {
          n -= 1;
          if (n > 0) { pad.textContent = String(n); return; }
          clearInterval(timer); phase = 'run'; taps = 0; pad.textContent = 'VIA!';
          const t0 = performance.now();
          timer = setInterval(() => {
            const left = 10 - (performance.now() - t0) / 1000;
            if (left > 0) { msg.textContent = `${left.toFixed(1)} s · ${taps} tocchi`; return; }
            clearInterval(timer); phase = 'done';
            msg.textContent = `Risultato: ${taps} tocchi in 10 s.`;
            pad.textContent = 'Salva';
          }, 100);
        }, 800);
      } else if (phase === 'run') {
        taps += 1;
      } else if (phase === 'done') {
        phase = 'saved'; saveCns('tap', taps).then(() => ov.remove());
      }
    });
  }

  // ------------------------------------------------------------ Oggi: matrice di prontezza
  const QUAD = {
    'alto/alto': { color: N.lime, label: 'Verde', text: 'Via libera ai lavori di qualità: ritmo maratona, ripetute, soglia.' },
    'alto/basso': { color: N.amber, label: 'Giallo', text: 'Corsa lenta in Z2 o rigenerante; niente ritmi veloci né lavori reattivi.' },
    'basso/alto': { color: N.amber, label: 'Giallo', text: 'Richiami brevi a ritmo gara sì; niente lunghissimi.' },
    'basso/basso': { color: N.pink, label: 'Rosso', text: 'Riposo attivo, camminata o scarico totale.' },
  };

  function drawReady() {
    const host = document.getElementById('prontezza-oggi');
    if (!host) return;
    const r = dash.data('readiness'), p = dash.data('goal_plan');
    if (r.status === 'error') { failed(host); return; }
    if (r.status !== 'ok' || !r.data.length) { host.hidden = r.status === 'ok'; return; }
    host.hidden = false;
    const a = r.data[r.data.length - 1];
    const w = 'date=' + a.date;
    const cnsKind = cnsState('cmj').value != null ? 'cmj' : 'tap';
    const cns = local ? cnsState(cnsKind) : null;
    const quad = a.ans_state && cns && cns.state ? QUAD[`${a.ans_state}/${cns.state}`] : null;

    const top = el('div', 'px-ready-top');
    const ansBox = el('div', 'px-sys');
    const rg = el('div', 'nx-ring px-ring');
    const t = ring(rg, a.ans_score, 96, 8); rg.prepend(rg.lastChild);
    const v = el('div', 'nx-ring-val'); v.append(mk('b', t.cls, a.ans_score == null ? '—' : f0(a.ans_score), 'readiness', 'ans_score', w), el('span', null, 'ANS'));
    rg.append(v);
    const ansTxt = el('div');
    ansTxt.append(el('div', 'px-sys-name', 'Sistema autonomo'), mk('b', 'px-state', a.ans_state || 'n/d', 'readiness', 'ans_state', w),
      el('p', 'nx-note', `HRV ${a.c_hrv == null ? '—' : f0(a.c_hrv)} · FC riposo ${a.c_rhr == null ? '—' : f0(a.c_rhr)} · sonno ${a.c_sleep == null ? '—' : f0(a.c_sleep)} (${fmtDay(parseDay(a.date))})`));
    if (a.red_flag) ansTxt.append(el('p', 'nx-note nx-s-low', 'HRV molto bassa e FC a riposo alta insieme.'));
    ansBox.append(rg, ansTxt);

    const cnsBox = el('div', 'px-sys');
    if (!local) {
      cnsBox.append(el('p', 'nx-note', 'Il test neuromuscolare (tapping o salto) si fa dalla web app sul telefono: il risultato resta sul dispositivo.'));
    } else {
      const c = el('div');
      c.append(el('div', 'px-sys-name', 'Sistema neuromuscolare'));
      if (cns.value == null) c.append(el('b', 'px-state', 'test da fare'));
      else {
        c.append(el('b', 'px-state', cns.state || `calibrazione ${cns.n}/5`));
        c.append(el('p', 'nx-note', `${cns.kind === 'cmj' ? 'Salto' : 'Tapping'} oggi ${cns.kind === 'cmj' ? f1(cns.value) + ' cm' : cns.value + ' tocchi'}` +
          (cns.mean ? ` · media 28 gg ${cns.kind === 'cmj' ? f1(cns.mean) : f0(cns.mean)}` : '')));
      }
      const btns = el('div', 'px-btns');
      const tap = el('button', 'gx-chip', 'Tapping test 10 s'); tap.addEventListener('click', tappingTest);
      const cmj = el('button', 'gx-chip', 'Salto CMJ (cm)');
      cmj.addEventListener('click', () => {
        const x = parseFloat(String(window.prompt('Altezza del salto CMJ in cm (es. 34.5):') || '').replace(',', '.'));
        if (isFinite(x) && x > 5 && x < 90) saveCns('cmj', x);
      });
      btns.append(tap, cmj);
      c.append(btns);
      cnsBox.append(c);
    }
    top.append(ansBox, cnsBox);

    // griglia 2x2
    const grid = el('div', 'px-matrix');
    grid.append(el('span'), el('span', 'px-mx-h', 'CNS alto'), el('span', 'px-mx-h', 'CNS basso'));
    for (const ans of ['alto', 'basso']) {
      grid.append(el('span', 'px-mx-h', `ANS ${ans}`));
      for (const c of ['alto', 'basso']) {
        const q = QUAD[`${ans}/${c}`];
        const cell = el('div', 'px-mx-cell', q.label);
        cell.style.color = q.color;
        const on = a.ans_state === ans && (!cns || !cns.state || cns.state === c);
        if (on) cell.classList.add(cns && cns.state ? 'px-on' : 'px-half');
        grid.append(cell);
      }
    }
    const rec = el('div', 'nx-coach px-advice');
    if (quad) { rec.style.borderLeftColor = quad.color; rec.append(el('b', null, `${quad.label}: `), quad.text); }
    else if (a.ans_state === 'basso') rec.append(el('b', null, 'Giallo/rosso: '), 'sistema autonomo basso; niente lunghissimi né lavori intensi. Il test neuromuscolare decide tra giallo e rosso.');
    else if (a.ans_state === 'alto') rec.append(el('b', null, 'Verde/giallo: '), 'sistema autonomo pronto; il test neuromuscolare decide se oggi va bene la qualità.');
    else rec.append('Dati del sistema autonomo non disponibili per oggi.');
    if (p.status === 'ok') {
      const plan = p.data.find((x) => x.status === 'oggi');
      if (plan) rec.append(el('br'), el('span', 'nx-note', 'Piano di oggi: '), mk('b', null, plan.title, 'goal_plan', 'title', 'date=' + plan.date));
    }
    const parts = [head('Prontezza', 'sistema autonomo × neuromuscolare'), top, grid, rec];
    if (a.impact_block) {
      const warn = el('div', 'px-impact');
      warn.append(el('b', null, 'Protezione strutturale attiva: '), mk('span', null, a.impact_reason || 'niente lavori ad alto impatto', 'readiness', 'impact_reason', w));
      parts.push(warn);
    }
    parts.push(evid(el('p', 'nx-note'), "Allenamento guidato dall'HRV [EMERGENTE] · salto CMJ come indice di fatica [EMERGENTE] · tapping test [PRELIMINARE MA RILEVANTE]"));
    host.replaceChildren(...parts);
  }

  // ------------------------------------------------------------ Oggi: carico cuore vs struttura
  function drawVectors() {
    const host = document.getElementById('carico-vettori');
    if (!host) return;
    const d = dash.data('load_vectors');
    if (d.status === 'error') { failed(host); return; }
    if (d.status !== 'ok' || !d.data.length) return;
    const rows = d.data.filter((r) => r.cardio_idx != null || r.struct_idx != null);
    const last = rows[rows.length - 1];
    if (!last) { host.replaceChildren(head('Carico cuore e struttura'), el('p', 'nx-note', 'Servono almeno 4 settimane di corse.')); return; }
    const w = 'date=' + last.date;
    const line = (label, field, raw, color, unit) => {
      const r = el('div', 'gl-part');
      const n = el('div', 'gl-part-name'); n.append(el('b', null, label));
      const v = el('div', 'gl-part-val');
      v.append(mk('b', 'gl-mono', last[field] == null ? '—' : f0(last[field]), 'load_vectors', field, w), el('span', 'nx-note', '° perc. · '),
        mk('span', 'gl-mono', f1(last[raw]), 'load_vectors', raw, w), el('span', 'nx-note', ` ${unit} in 7 gg`));
      r.append(n, v, bar(last[field], color));
      return r;
    };
    const chart = el('div', 'nx-chart px-vec-chart');
    const parts = [head('Carico cuore e struttura', 'percentile dei 7 giorni rispetto al tuo storico'),
      line('Cardiovascolare (TRIMP)', 'cardio_idx', 'cardio_7d', N.magenta, 'TRIMP'),
      line('Strutturale (gambe)', 'struct_idx', 'mech_7d', N.amber, 'kBW'), chart];
    if (last.impact_block) { const x = el('div', 'px-impact'); x.append(el('b', null, 'Protezione attiva: '), mk('span', null, last.reason, 'load_vectors', 'reason', w)); parts.push(x); }
    parts.push(evid(el('p', 'nx-note'), 'TRIMP di Edwards [CONSOLIDATO] · carico strutturale da modello molla-massa e discese [PRELIMINARE MA RILEVANTE]'));
    host.replaceChildren(...parts);
    const D = rows.slice(-60).map((r) => ({ ...r, _d: parseDay(r.date) }));
    nxChart(chart, {
      xType: 'time', height: 140, yDomain: [0, 100], yFmt: f0,
      series: [
        { type: 'line', name: 'Cuore', color: N.magenta, fmt: (v) => f0(v) + '°', data: D.map((r) => ({ x: r._d, y: r.cardio_idx })) },
        { type: 'line', name: 'Struttura', color: N.amber, fmt: (v) => f0(v) + '°', data: D.map((r) => ({ x: r._d, y: r.struct_idx })) },
      ],
    });
  }

  // ------------------------------------------------------------ carburante (Oggi e report)
  function fuelBlock(f, title) {
    const w = 'id=' + f.id;
    const box = el('div', 'nx-card px-fuel');
    box.append(head(title, `${fmtDay(parseDay(f.date))} · stima dal costo della corsa e dalla FC`));
    const stats = el('div', 'nx-stats');
    [['Energia', 'kcal', ' kcal'], ['Carboidrati', 'cho_g', ' g'], ['Grassi', 'fat_g', ' g'], ['Glicogeno usato', 'glycogen_used_pct', '%']].forEach(([l, k, u]) => {
      const d = el('div', 'nx-stat'); d.append(el('span', null, l), mk('b', null, (f[k] == null ? '—' : f0(f[k])) + u, 'fuel', k, w)); stats.append(d);
    });
    const split = el('div', 'px-split');
    const tot = (f.cho_easy_g || 0) + (f.cho_steady_g || 0) + (f.cho_hard_g || 0) || 1;
    [['cho_easy_g', 'sotto LT1', N.cyan], ['cho_steady_g', 'LT1-LT2', N.amber], ['cho_hard_g', 'sopra LT2', N.pink]].forEach(([k, l, c]) => {
      const s = el('span', 'px-split-seg'); s.style.flexGrow = String(f[k] || 0); s.style.background = c; s.title = `${l}: ${f[k]} g`;
      if ((f[k] || 0) / tot > 0.12) s.textContent = `${l} ${f[k]} g`;
      split.append(s);
    });
    const target = el('div', 'nx-coach');
    target.style.borderLeftColor = f.urgent ? N.amber : N.lime;
    target.append(evid(mk('span', null, '', 'fuel', 'target_text', w), f.target_text));
    box.append(stats, el('div', 'nx-note', 'Carboidrati per intensità'), split, target,
      evid(el('p', 'nx-note'), `Scorta stimata ${f.glycogen_store_g} g (7 g/kg) [EMERGENTE]; gel presi in corsa non inclusi.`));
    return box;
  }

  function drawFuelToday() {
    const host = document.getElementById('carburante-oggi');
    if (!host) return;
    const d = dash.data('fuel');
    if (d.status === 'error') { failed(host); return; }
    if (d.status !== 'ok') return;
    const t = Date.parse(today());
    const f = [...d.data].reverse().find((x) => (t - Date.parse(x.date)) / 864e5 <= 1.5);
    host.hidden = !f;
    if (f) host.replaceChildren(...fuelBlock(f, 'Carburante').childNodes);
  }

  // ------------------------------------------------------------ report della corsa
  function drawRunPerf() {
    const box = document.getElementById('report-corsa');
    const host = box && box.querySelector('.nx-perf-run');
    if (!host || box.hidden) return;
    const id = S.sel;
    const L = dash.data('run_load'), F = dash.data('fuel'), B = dash.data('biomech');
    const cards = [];
    const l = L.status === 'ok' && L.data.find((r) => r.id === id);
    if (l) {
      const w = 'id=' + l.id;
      const c = el('div', 'nx-card');
      c.append(head('Carico della corsa', 'percentile rispetto alle corse dei 120 gg precedenti'));
      [['Cuore (TRIMP)', 'cardio_si', 'trimp', '', N.magenta], ['Struttura (kBW)', 'struct_si', 'mech_kbw', '', N.amber]].forEach(([lab, si, raw, u, col]) => {
        const r = el('div', 'gl-part');
        const n = el('div', 'gl-part-name'); n.append(el('b', null, lab));
        const v = el('div', 'gl-part-val'); v.append(mk('b', 'gl-mono', l[si] == null ? '—' : f0(l[si]), 'run_load', si, w), el('span', 'nx-note', '° · '), mk('span', 'gl-mono', l[raw] == null ? '—' : f1(l[raw]), 'run_load', raw, w));
        r.append(n, v, bar(l[si], col)); c.append(r);
      });
      const dl = el('p', 'nx-sec-note');
      dl.append(`Picco di forza medio ${l.f_peak_bw} × peso (${l.mech_method}) · ${l.steps} passi`,
        l.descent_m != null ? ` · discesa ${l.descent_m} m (${l.descent_method}, fattore ${l.downhill_factor})` : '',
        l.asym_factor > 1 ? ` · asimmetria ×${l.asym_factor}` : '');
      c.append(dl);
      if (l.impact_block) { const x = el('div', 'px-impact'); x.append(mk('span', null, l.note, 'run_load', 'note', w)); c.append(x); }
      cards.push(c);
    }
    const f = F.status === 'ok' && F.data.find((r) => r.id === id);
    if (f) cards.push(fuelBlock(f, 'Carburante'));
    const b = B.status === 'ok' && B.data.find((r) => r.id === id);
    if (b) {
      const w = 'id=' + b.id;
      const c = el('div', 'nx-card');
      c.append(head('Deriva biomeccanica', 'ultimo terzo vs primo, dopo 5 minuti'));
      const tb = el('table', 'gx-table px-drift');
      const tr0 = el('tr'); ['', 'inizio', 'finale', 'variazione'].forEach((x) => tr0.append(el('th', x ? 'num' : null, x)));
      const th = el('thead'); th.append(tr0);
      const body = el('tbody');
      [['Cadenza (ppm)', 'cad', f0], ['Contatto (ms)', 'gct', f0], ['Oscillazione (cm)', 'vo', f1]].forEach(([lab, k, fmt]) => {
        const tr = el('tr');
        tr.append(el('td', null, lab), mk('td', 'num', b[k + '_first'] == null ? '—' : fmt(b[k + '_first']), 'biomech', k + '_first', w),
          mk('td', 'num', b[k + '_last'] == null ? '—' : fmt(b[k + '_last']), 'biomech', k + '_last', w),
          mk('td', 'num', b[k + '_chg'] == null ? '—' : (b[k + '_chg'] > 0 ? '+' : '') + f1(b[k + '_chg']) + '%', 'biomech', k + '_chg', w));
        body.append(tr);
      });
      if (b.has_balance) {
        const tr = el('tr');
        tr.append(el('td', null, 'Appoggio sinistro (%)'), mk('td', 'num', f1(b.bal_first), 'biomech', 'bal_first', w), mk('td', 'num', f1(b.bal_last), 'biomech', 'bal_last', w),
          el('td', 'num', (b.bal_last - b.bal_first > 0 ? '+' : '') + f1(b.bal_last - b.bal_first) + ' pt'));
        body.append(tr);
      }
      tb.append(th, body);
      const note = el('div', 'nx-coach');
      note.style.borderLeftColor = b.alert ? N.pink : N.lime;
      note.append(evid(el('span'), b.note));
      c.append(tb, note);
      cards.push(c);
    }
    host.replaceChildren(...cards);
  }

  // ------------------------------------------------------------ Obiettivo: modello di scarico
  function drawTaper() {
    const card = document.getElementById('gl-taper-card');
    if (!card || S.page !== 'obiettivo') return;
    const t = dash.data('taper'), m = dash.data('taper_meta');
    const chart = card.querySelector('#gl-taper-chart');
    if (t.status === 'error') { failed(chart); return; }
    if (t.status !== 'ok') return;
    if (!t.data.length) { card.hidden = true; return; }
    card.hidden = false;
    const D = t.data.map((r) => ({ ...r, _d: parseDay(r.date) }));
    const race = D.find((r) => r.is_race), peak = D.find((r) => r.is_peak);
    nxChart(chart, {
      xType: 'time', height: 220, yDomain: [0, 100], yFmt: f0,
      refLines: [],
      series: [
        { type: 'bars', name: 'Carico (TSS)', color: N.violet, fmt: f0, data: D.map((r) => ({ x: r._d, y: Math.min(100, r.tss / 2.5), label: `${f0(r.tss)} TSS${r.projected ? ' previsto' : ''}` })) },
        { type: 'area', name: 'Forma', color: N.cyan, fmt: (v) => f0(v), data: D.map((r) => ({ x: r._d, y: r.projected ? null : r.perf_idx })) },
        { type: 'line', name: 'Forma prevista', color: N.cyan, opacity: 0.55, fmt: (v) => f0(v), data: D.map((r, i) => ({ x: r._d, y: r.projected || (D[i + 1] && D[i + 1].projected) ? r.perf_idx : null })) },
        { type: 'dots', name: 'Picco', color: N.lime, r: 6, opacity: 1, fmt: (v) => f0(v), data: peak ? [{ x: peak._d, y: peak.perf_idx, label: fmtDay(peak._d) }] : [] },
        { type: 'dots', name: 'Gara', color: N.amber, r: 6, opacity: 1, fmt: (v) => f0(v), data: race ? [{ x: race._d, y: race.perf_idx, label: 'giorno della gara' }] : [] },
      ],
    });
    const meta = m.status === 'ok' && m.data[0];
    const info = card.querySelector('.gl-taper-info');
    info.replaceChildren();
    if (meta) {
      const line = el('p', 'nx-note');
      line.append('Picco previsto ', mk('b', null, meta.peak_date ? fmtDay(parseDay(meta.peak_date)) : '—', 'taper_meta', 'peak_date'),
        ' · gara ', mk('b', null, fmtDay(parseDay(meta.race_date)), 'taper_meta', 'race_date'),
        ' · costanti: forma ', mk('b', 'gl-mono', f1(meta.tau1), 'taper_meta', 'tau1'), ` gg (${meta.tau1_source}), fatica `,
        mk('b', 'gl-mono', f1(meta.tau2), 'taper_meta', 'tau2'), ` gg (${meta.tau2_source}) · ${meta.deload_weeks} settimane di scarico nello storico`);
      const note = el('div', 'nx-coach');
      note.append(evid(mk('span', null, '', 'taper_meta', 'note'), meta.note));
      info.append(line, note);
    }
  }

  function draw() {
    if (S.page === 'oggi') { drawReady(); drawVectors(); drawFuelToday(); }
    if (S.page === 'allenamenti') drawRunPerf();
    drawTaper();
  }
  const base = window.gxDraw;
  window.gxDraw = () => { base(); draw(); };
  dash.onData(draw);
})();
