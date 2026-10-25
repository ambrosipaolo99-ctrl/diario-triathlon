// ============================================================== Oggi: allenamenti della giornata
// Una card per ogni attivita' con la data di oggi (di chi guarda): voto del preparatore e voci.
(() => {
  const { N, ring, tier, el, markEl, failed } = window.nx;
  const S = window.gxState;
  const f0 = d3.format('.0f'), f1 = d3.format('.1f');
  const mk = (tag, cls, text, field, where, src = 'today') => markEl(el(tag, cls, text), src, field, where);
  const hm = (min) => { const t = Math.round(min); return t >= 60 ? `${Math.floor(t / 60)}h${String(t % 60).padStart(2, '0')}` : `${t}'`; };
  const KIND = { Facile: N.cyan, 'Qualità': N.magenta, Lungo: N.lime, Gara: N.amber };
  const localDay = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

  function group(name, score, weight, parts, r) {
    const box = el('div', 'nx-card td-group');
    const head = el('div', 'nx-card-head');
    const t = tier(score);
    const val = el('span', 'td-group-score');
    val.append(mk('b', 'gl-mono ' + t.cls, score == null ? '—' : String(score), name.startsWith('Esec') ? 'exec_score' : 'tech_score', 'id=' + r.id));
    if (weight != null) val.append(el('span', 'nx-note', ` · peso ${weight}%`));
    head.append(el('h3', null, name), val);
    const list = el('div', 'gl-parts');
    list.append(...parts.map((q) => {
      const k = 'key=' + q.key;
      const tt = tier(q.score);
      const row = el('div', 'gl-part' + (q.score == null ? ' gl-na' : ''));
      const nm = el('div', 'gl-part-name');
      nm.append(mk('b', null, q.component, 'component', k, 'today_parts'), ' ', el('span', 'nx-note', 'peso '),
        mk('span', 'nx-note', String(q.weight), 'weight', k, 'today_parts'), el('span', 'nx-note', '%'));
      const v = el('div', 'gl-part-val');
      v.append(mk('b', 'gl-mono ' + tt.cls, q.score == null ? 'n/d' : String(q.score), 'score', k, 'today_parts'));
      if (q.value) v.append(' · ', mk('span', 'gl-mono', q.value, 'value', k, 'today_parts'));
      const bar = el('div', 'gl-bar'); const fill = el('span'); fill.style.width = (q.score ?? 0) + '%'; fill.style.background = tt.color; fill.style.color = tt.color; bar.append(fill);
      row.append(nm, v, bar);
      if (q.note) row.append(mk('p', 'nx-sec-note', q.note, 'note', k, 'today_parts'));
      return row;
    }));
    box.append(head, list);
    return box;
  }

  function card(r, parts) {
    const w = 'id=' + r.id;
    const c = el('article', 'nx-card td-card');
    // intestazione
    const top = el('div', 'td-top');
    const ringHost = el('div', 'nx-ring td-ring');
    const val = el('div', 'nx-ring-val');
    const t = tier(r.score);
    val.append(mk('b', t.cls, r.score == null ? '—' : String(r.score), 'score', w), el('span', null, r.score == null ? 'senza voto' : t.label));
    ringHost.append(val);
    ring(ringHost, r.score, 112, 9);
    ringHost.prepend(ringHost.lastChild);
    const title = el('div', 'nx-title');
    title.append(el('span', 'nx-eyebrow', 'Allenamento di oggi'), mk('h2', 'td-name', r.name || r.sport_label, 'name', w));
    const meta = el('p', 'nx-note td-meta');
    meta.append(`ore ${r.start.slice(11, 16)} · `, mk('span', null, r.sport_label, 'sport_label', w));
    if (r.kind) {
      const k = mk('span', 'gl-type', r.kind, 'kind', w); k.style.color = KIND[r.kind] || N.muted;
      meta.append(' · ', k);
    }
    if (r.plan_title) meta.append(' · piano: ', mk('b', null, r.plan_title, 'plan_title', w));
    title.append(meta);
    top.append(ringHost, title);
    c.append(top);
    // numeri
    const stats = el('div', 'nx-stats');
    const stat = (label, node) => { const d = el('div', 'nx-stat'); d.append(el('span', null, label), node); stats.append(d); };
    if (r.distance_km) stat('Distanza', mk('b', null, f1(r.distance_km) + ' km', 'distance_km', w));
    stat('Durata', mk('b', null, hm(r.duration_min), 'duration_min', w));
    if (r.sport === 'run' && r.pace) stat('Passo', mk('b', null, r.pace, 'pace', w));
    if (r.avg_hr) stat('FC media', mk('b', null, f0(r.avg_hr) + ' bpm', 'avg_hr', w));
    if (r.ascent_m != null) {
      const b = el('b'); b.append(mk('span', null, '+' + f0(r.ascent_m) + ' m', 'ascent_m', w));
      const src = mk('span', 'td-src', r.ascent_source === 'strava' ? 'Strava' : 'orologio', 'ascent_source', w);
      stat('Dislivello', b); stats.lastChild.append(src);
    } else if (r.ascent_source === 'in attesa di Strava') {
      stat('Dislivello', mk('b', 'td-wait', 'in attesa di Strava', 'ascent_source', w));
    }
    if (r.tss != null) stat('TSS', mk('b', null, f0(r.tss), 'tss', w));
    c.append(stats);
    if (r.comment) c.append(mk('div', 'nx-coach', r.comment, 'comment', w));
    // voci del voto, per blocco
    const mine = parts.filter((q) => q.activity_id === r.id);
    const groups = d3.groups(mine, (q) => q.group);
    if (groups.length) {
      const g = el('div', 'nx-grid td-groups');
      groups.forEach(([name, ps]) => {
        const score = name.startsWith('Esec') ? r.exec_score : name.startsWith('Tecn') ? r.tech_score : r.score;
        const weight = name.startsWith('Esec') ? r.exec_weight : name.startsWith('Tecn') ? r.tech_weight : null;
        g.append(group(name, score, weight, ps, r));
      });
      c.append(g);
    } else if (r.score == null) {
      c.append(el('p', 'nx-note', 'Attività registrata: per questo sport non c\'è un voto.'));
    }
    const go = el('button', 'gx-chip', 'Apri il report completo →');
    go.addEventListener('click', () => { S.sel = r.id; window.gxShow('allenamenti'); document.getElementById('dettaglio-allenamento').scrollIntoView({ block: 'start' }); });
    c.append(go);
    return c;
  }

  function drawTodayActs() {
    const host = document.getElementById('allenamenti-oggi');
    const d = dash.data('today'), p = dash.data('today_parts');
    if (d.status === 'error') { host.hidden = false; failed(host); return; }
    if (d.status !== 'ok') { host.hidden = true; return; }
    const rows = d.data.filter((r) => r.date === localDay()).sort((a, b) => a.start.localeCompare(b.start));
    host.hidden = !rows.length;
    if (!rows.length) { host.replaceChildren(); return; }
    if (p.status === 'error') { failed(host); return; }
    host.replaceChildren(...rows.map((r) => card(r, p.status === 'ok' ? p.data : [])));
  }

  dash.onData(drawTodayActs);
})();
