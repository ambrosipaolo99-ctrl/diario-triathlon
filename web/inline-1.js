// ---------------------------------------------------------------- utilità
window.gx = (() => {
  const loc = d3.timeFormatLocale({
    dateTime: '%A %e %B %Y, %X', date: '%d/%m/%Y', time: '%H:%M:%S', periods: ['AM', 'PM'],
    days: ['domenica', 'lunedì', 'martedì', 'mercoledì', 'giovedì', 'venerdì', 'sabato'],
    shortDays: ['dom', 'lun', 'mar', 'mer', 'gio', 'ven', 'sab'],
    months: ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre'],
    shortMonths: ['gen', 'feb', 'mar', 'apr', 'mag', 'giu', 'lug', 'ago', 'set', 'ott', 'nov', 'dic'],
  });
  const parseDay = d3.utcParse('%Y-%m-%d');
  const parseTs = (s) => new Date(s.slice(0, 19) + 'Z');
  const fmtDay = loc.utcFormat('%-d %b %Y');
  const fmtDayShort = loc.utcFormat('%-d %b');
  const fmtDayTime = loc.utcFormat('%-d %b %Y, %H:%M');
  const f0 = d3.format('.0f'), f1 = d3.format('.1f'), f2 = d3.format('.2f');
  const cls = (v) => v == null ? '' : v >= 75 ? 'gx-ok' : v >= 55 ? 'gx-warn' : 'gx-bad';
  const dur = (min) => { if (min == null) return '—'; const m = Math.round(min); return `${Math.floor(m / 60)}:${String(m % 60).padStart(2, '0')}`; };
  const rolling = (rows, key, days, dateKey = 'date') => {
    const out = [];
    rows.forEach((r, i) => {
      const t = r._d.getTime(), w = [];
      for (let j = i; j >= 0 && t - rows[j]._d.getTime() < days * 864e5; j--) if (rows[j][key] != null) w.push(rows[j][key]);
      out.push(w.length >= Math.min(3, days) ? d3.mean(w) : null);
    });
    return out;
  };
  const failed = (el) => { el.replaceChildren(); const d = document.createElement('div'); d.className = 'gx-fail'; d.textContent = 'Failed to load'; el.append(d); };

  // grafico temporale: series = [{type:'line'|'bar'|'dots'|'step'|'band', data:[{x,y,y2?}], color, name, fmt}]
  function timeChart(el, { series, height = 220, yDomain, refLines = [], yFmt = f0, xDomain }) {
    el.replaceChildren();
    const W = el.clientWidth;
    if (!W) return;
    const all = series.flatMap((s) => s.data);
    if (!all.length) { const p = document.createElement('p'); p.className = 'gx-note'; p.textContent = 'Nessun dato nel periodo.'; el.append(p); return; }
    const xd = xDomain || d3.extent(all, (d) => d.x);
    let yd = yDomain;
    if (!yd) {
      const lo = d3.min(all, (d) => Math.min(d.y ?? Infinity, d.y2 ?? Infinity));
      const hi = d3.max(all, (d) => Math.max(d.y ?? -Infinity, d.y2 ?? -Infinity));
      const hasBar = series.some((s) => s.type === 'bar');
      yd = [hasBar ? Math.min(0, lo) : lo - (hi - lo) * 0.08, hi + (hi - lo) * 0.08 || 1];
    }
    const y0 = d3.scaleLinear(yd, [height - 24, 8]).nice(4);
    const ticks = y0.ticks(4);
    const svg = d3.select(el).append('svg').attr('width', '100%').attr('height', height).attr('viewBox', `0 0 ${W} ${height}`);
    const probe = svg.append('text').attr('font-size', 12);
    const ml = 8 + d3.max(ticks, (t) => { probe.text(yFmt(t)); return probe.node().getComputedTextLength(); });
    probe.remove();
    const x = d3.scaleUtc(xd, [ml, W - 8]);
    const y = y0;
    const g = svg.append('g');
    g.selectAll('line.grid').data(ticks).join('line').attr('x1', ml).attr('x2', W - 8).attr('y1', (t) => y(t)).attr('y2', (t) => y(t)).attr('stroke', 'var(--cds-chart-grid)');
    g.selectAll('text.yt').data(ticks).join('text').attr('x', ml - 6).attr('y', (t) => y(t)).attr('dy', '0.32em').attr('text-anchor', 'end').attr('font-size', 12).attr('fill', 'var(--color-fg-muted)').text(yFmt);
    const xt = x.ticks(Math.max(2, Math.floor(W / 110)));
    g.selectAll('text.xt').data(xt).join('text').attr('x', (t) => x(t)).attr('y', height - 6).attr('text-anchor', 'middle').attr('font-size', 12).attr('fill', 'var(--color-fg-muted)').text(fmtDayShort);
    const [dlo, dhi] = y.domain();
    const base = dlo <= 0 && dhi >= 0 ? 0 : dlo;
    g.append('line').attr('x1', ml).attr('x2', W - 8).attr('y1', y(base)).attr('y2', y(base)).attr('stroke', 'var(--cds-chart-axis)');
    refLines.forEach((v) => g.append('line').attr('x1', ml).attr('x2', W - 8).attr('y1', y(v)).attr('y2', y(v)).attr('stroke', 'var(--cds-chart-reference)').attr('stroke-dasharray', '4 4'));
    const day = Math.max(1, (x(new Date(xd[0].getTime() + 864e5)) - x(xd[0])));
    for (const s of series) {
      const d = s.data.filter((p) => p.y != null || s.type === 'band');
      if (s.type === 'band') {
        g.append('path').datum(d.filter((p) => p.y != null && p.y2 != null)).attr('fill', s.color).attr('opacity', 0.14)
          .attr('d', d3.area().defined((p) => p.y != null).x((p) => x(p.x)).y0((p) => y(p.y)).y1((p) => y(p.y2)));
      } else if (s.type === 'bar') {
        const bw = Math.max(1, Math.min(14, day * 0.7));
        g.selectAll(null).data(d).join('rect').attr('x', (p) => x(p.x) - bw / 2).attr('width', bw)
          .attr('y', (p) => Math.min(y(p.y), y(0))).attr('height', (p) => Math.abs(y(0) - y(p.y))).attr('rx', Math.min(2, bw / 2)).attr('fill', s.color);
      } else if (s.type === 'dots') {
        g.selectAll(null).data(d).join('circle').attr('cx', (p) => x(p.x)).attr('cy', (p) => y(p.y)).attr('r', 4)
          .attr('fill', s.color).attr('fill-opacity', s.opacity ?? 0.6).attr('stroke', 'var(--color-panel)').attr('stroke-width', 1.5);
      } else {
        g.append('path').datum(d).attr('fill', 'none').attr('stroke', s.color).attr('stroke-width', 2).attr('stroke-linejoin', 'round').attr('stroke-linecap', 'round')
          .attr('d', d3.line().defined((p) => p.y != null).x((p) => x(p.x)).y((p) => y(p.y)).curve(s.type === 'step' ? d3.curveStepAfter : d3.curveLinear));
      }
    }
    // tooltip: punto piu' vicino sull'asse x
    const tip = document.createElement('div'); tip.className = 'gx-tip'; tip.hidden = true; el.append(tip);
    const rule = g.append('line').attr('y1', 8).attr('y2', height - 24).attr('stroke', 'var(--cds-chart-axis)').attr('opacity', 0);
    const xs = [...new Set(all.map((p) => +p.x))].sort((a, b) => a - b);
    const bis = d3.bisector((v) => v).center;
    svg.append('rect').attr('x', ml).attr('y', 0).attr('width', W - ml).attr('height', height).attr('fill', 'transparent')
      .on('pointermove', (ev) => {
        const [mx] = d3.pointer(ev);
        const t = xs[bis(xs, +x.invert(mx))];
        // costruito con nodi di testo: i nomi delle attivita' sono dati, non markup
        const lines = series.filter((s) => s.name && s.type !== 'band').map((s) => {
          const p = s.data.find((q) => +q.x === t && q.y != null);
          if (!p) return null;
          const row = document.createElement('div');
          const sw = document.createElement('span'); sw.className = 'sw'; sw.style.background = s.color;
          const b = document.createElement('b'); b.textContent = (s.fmt || yFmt)(p.y);
          row.append(sw, s.name + ' ', b, p.label ? ' · ' + p.label : '');
          return row;
        }).filter(Boolean);
        if (!lines.length) { tip.hidden = true; return; }
        const head = document.createElement('div'); head.className = 'd'; head.textContent = fmtDay(new Date(t));
        tip.replaceChildren(head, ...lines);
        tip.hidden = false;
        rule.attr('x1', x(t)).attr('x2', x(t)).attr('opacity', 1);
        const tw = tip.offsetWidth;
        tip.style.left = Math.max(0, Math.min(W - tw, x(t) + 10 + tw > W ? x(t) - tw - 10 : x(t) + 10)) + 'px';
        tip.style.top = '8px';
      })
      .on('pointerleave', () => { tip.hidden = true; rule.attr('opacity', 0); });
  }
  return { loc, parseDay, parseTs, fmtDay, fmtDayTime, f0, f1, f2, cls, dur, rolling, timeChart, failed };
})();
