// ---------------------------------------------------------------- disegno
(() => {
  const { loc, parseDay, parseTs, fmtDay, fmtDayTime, f0, f1, f2, cls, dur, rolling, timeChart, failed } = window.gx;
  const S = window.gxState;
  const C = dash.colors;
  const setText = (sel, v, fmt = (x) => x) => document.querySelectorAll(sel).forEach((el) => { el.textContent = v == null ? '—' : fmt(v); el.classList.remove('dash-skeleton'); });
  const mark = (root, ds, where) => root.querySelectorAll(`[data-source="${ds}"][data-field]`).forEach((el) => el.setAttribute('data-where', where));

  function drawToday(w, l) {
    const wellness = w.data.filter((r) => r.recovery != null);
    const root = document.getElementById('oggi');
    const take = document.querySelector('.gx-take-text');
    if (w.status === 'error') take.classList.remove('dash-skeleton');
    if (w.status === 'ok' && wellness.length) {
      const r = wellness[wellness.length - 1];
      const where = 'date=' + r.date;
      mark(root, 'wellness', where);
      mark(take, 'wellness', where);
      setText('.gx-take-label', r.recovery_label);
      setText('.gx-take-lim', r.limiter_label);
      take.classList.remove('dash-skeleton');
      setText('.gx-today-date', r.date, (d) => fmtDay(parseDay(d)));
      const rec = root.querySelector('.gx-today-rec');
      setText('.gx-today-rec', r.recovery, f0);
      rec.className = 'gx-today-rec ' + cls(r.recovery);
      setText('.gx-today-label', r.recovery_label);
      setText('.gx-today-lim', r.limiter_label);
      root.querySelectorAll('.gx-tile').forEach((tile) => {
        const k = tile.dataset.comp, v = r['c_' + k];
        const sc = tile.querySelector('.gx-tile-score');
        sc.textContent = v == null ? '—' : f0(v);
        sc.className = 'gx-tile-score ' + cls(v);
        tile.querySelector('.gx-meter > span').style.width = (v ?? 0) + '%';
        tile.querySelectorAll('.gx-tile-raw [data-field]').forEach((el) => {
          const f = el.dataset.field, x = r[f];
          el.textContent = x == null ? '—' : f === 'sleep_h' ? f1(x) : f0(x);
        });
      });
    }

    const card = document.getElementById('forma-oggi');
    if (l.status === 'ok' && l.data.length) {
      const r = l.data[l.data.length - 1];
      mark(card, 'load', 'date=' + r.date);
      card.querySelectorAll('[data-field]').forEach((el) => {
        const v = r[el.dataset.field];
        el.textContent = v == null ? '—' : el.dataset.field === 'acwr' ? f2(v) : f0(v);
      });
      const acwr = card.querySelector('[data-field="acwr"]');
      acwr.className = 'gx-tile-score ' + (r.acwr == null ? '' : r.acwr > 1.5 ? 'gx-bad' : r.acwr > 1.3 || r.acwr < 0.8 ? 'gx-warn' : 'gx-ok');
    }
  }

  function drawActivities(a, c) {
    document.querySelectorAll('[data-sport]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.sport === S.sport)));
    const tb = document.querySelector('.gx-acts tbody');
    if (a.status !== 'ok') { if (a.status === 'error') failed(tb.closest('.gx-tablebox')); return; }
    let rows = a.data.filter((r) => !r.duplicate);
    if (S.sport !== 'all') rows = rows.filter((r) => r.sport === S.sport);
    if (S.search) rows = rows.filter((r) => (r.name || '').toLowerCase().includes(S.search));
    const k = S.sort.key, dir = S.sort.dir;
    rows.sort((p, q) => {
      const x = p[k], y = q[k];
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === 'number' ? x - y : String(x).localeCompare(String(y))) * dir || (p.start < q.start ? 1 : -1);
    });
    document.querySelectorAll('.gx-acts th').forEach((th) => th.setAttribute('aria-sort', th.dataset.field === k ? (dir > 0 ? 'ascending' : 'descending') : 'none'));
    if (!S.sel && rows.length) S.sel = (rows.find((r) => r.score != null) || rows[0]).id;
    tb.replaceChildren(...rows.map((r) => {
      const tr = document.createElement('tr');
      tr.dataset.key = r.id; tr.tabIndex = 0;
      if (r.id === S.sel) tr.classList.add('sel');
      const cells = [
        [fmtDay(parseDay(r.date)), ''],
        [r.sport_label, ''],
        [r.name || '', 'wrap'],
        [f0(r.duration_min), 'num'],
        [r.distance_km ? f1(r.distance_km) : '—', 'num gx-hide-narrow'],
        [r.score == null ? '—' : f0(r.score), 'num ' + cls(r.score)],
        [r.tss == null ? '—' : f0(r.tss), 'num gx-hide-narrow'],
      ];
      cells.forEach(([t, cl]) => { const td = document.createElement('td'); td.textContent = t; if (cl) td.className = cl; tr.append(td); });
      return tr;
    }));

    // dettaglio
    const det = document.getElementById('dettaglio-allenamento');
    const r = a.data.find((q) => q.id === S.sel);
    if (!r) return;
    mark(det, 'activities', 'id=' + r.id);
    setText('.gx-det-title', r.name);
    setText('.gx-det-sport', r.sport_label);
    setText('.gx-det-date', r.start, (s) => fmtDayTime(parseTs(s)));
    setText('.gx-det-dur', r.duration_min, f0);
    const ds = det.querySelector('.gx-det-score');
    ds.textContent = r.score == null ? '—' : f0(r.score); ds.className = 'gx-det-score ' + cls(r.score);
    setText('.gx-det-conf', r.confidence, (v) => d3.format('.0%')(v));
    setText('.gx-det-tss', r.tss, f0);
    setText('.gx-det-tssm', r.tss_method);
    const FIELDS = {
      run: [['pace', 'Passo medio'], ['avg_hr', 'FC media', f0], ['ef_speed', 'Efficiency Factor', f2], ['decoupling_pct', 'Deriva cardiaca %', f1], ['pace_cv_pct', 'Variabilità passo %', f1], ['cadence_spm', 'Cadenza (passi/min)', f0], ['gct_ms', 'Contatto al suolo (ms)', f0], ['gct_balance_left', 'Bilanciamento GCT sx %', f1], ['vertical_ratio', 'Rapporto verticale %', f1]],
      bike: [['avg_power', 'Potenza media (W)', f0], ['np', 'Potenza normalizzata (W)', f0], ['if', 'Intensity Factor', f2], ['vi', 'Variability Index', f2], ['ftp', 'FTP usata (W)', f0], ['lr_left', 'Bilanciamento sx %', f1], ['best_5min', "Miglior 5' (W)", f0], ['best_20min', "Miglior 20' (W)", f0], ['best_60min', "Miglior 60' (W)", f0], ['avg_hr', 'FC media', f0], ['ef_power', 'NP / FC', f2], ['decoupling_pct', 'Decoupling Pw:HR %', f1]],
      swim: [['pace_100m_s', 'Passo /100 m', (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`], ['swolf', 'SWOLF medio', f1], ['swolf_cv_pct', 'Variabilità SWOLF %', f1], ['stroke_rate', 'Bracciate/min', f0], ['pace_cv_pct', 'Variabilità passo %', f1], ['avg_hr', 'FC media', f0]],
      other: [['avg_hr', 'FC media', f0]],
    };
    const dl = det.querySelector('.gx-det-metrics');
    dl.replaceChildren(...(FIELDS[r.sport] || []).filter(([f]) => r[f] != null).map(([f, label, fmt]) => {
      const div = document.createElement('div');
      const dt = document.createElement('dt'); dt.textContent = label;
      const dd = document.createElement('dd');
      dd.setAttribute('data-source', 'activities'); dd.setAttribute('data-field', f); dd.setAttribute('data-where', 'id=' + r.id);
      const v = r[f]; dd.textContent = fmt ? fmt(v) : String(v);
      div.append(dt, dd); return div;
    }));
  }

  window.gxDraw = () => {
    const w = dash.data('wellness'), l = dash.data('load'), a = dash.data('activities'), c = dash.data('components');
    drawToday(w, l);
    drawActivities(a, c);
  };
  dash.onData(window.gxDraw);
})();
