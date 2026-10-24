// ============================================================== La carica: personaggi anime e frasi motivazionali
// Frasi dei personaggi: originali, in inglese, scritte nello spirito di ognuno (non citazioni dalle opere).
// Fascia "Legends": citazioni reali di atleti, con attribuzione.
// tags = tipi di allenamento a cui si adatta: facile, qualità, lungo, gara, riposo.
// img = chiave in window.CK_IMG (ritagli generati da scripts/build_carica_images.py).
(() => {
  const { el, markEl } = window.nx;
  const S = window.gxState;
  Object.assign(S, { caricaOffset: 0, caricaPick: null });
  const IMG = window.CK_IMG || {};

  const SERIES = {
    db: { name: 'Dragon Ball', color: '#ff9f1c' },
    op: { name: 'One Piece', color: '#ff3b3b' },
    na: { name: 'Naruto', color: '#ff7a00' },
    vs: { name: 'Vinland Saga', color: '#7fb3d5' },
    vg: { name: 'Vagabond', color: '#c9b37e' },
    hh: { name: 'Hunter × Hunter', color: '#3ddc84' },
    hq: { name: 'Haikyu!!', color: '#ff8c1a' },
    ip: { name: 'Hajime no Ippo', color: '#e8e8e8' },
  };
  const CREW = [
    // Dragon Ball
    { who: 'Goku', s: 'db', icon: '⚡', img: 'goku_ssj', tags: ['qualità', 'gara'], line: 'Your limit today is your warm-up tomorrow.' },
    { who: 'Goku', s: 'db', icon: '⚡', img: 'goku_panels', tags: ['facile', 'riposo'], line: 'Even Saiyans rest. Power is built in the recovery.' },
    { who: 'Goku', s: 'db', icon: '⚡', img: 'goku_god', tags: ['lungo', 'qualità'], line: 'Bent over, out of breath, and still getting up. That\'s where it pays off.' },
    { who: 'Vegito', s: 'db', icon: '💥', img: 'vegito_blue', tags: ['gara', 'facile'], line: 'Wake up. Show up. Feelings are optional. The miles aren\'t.' },
    { who: 'Vegito', s: 'db', icon: '💥', img: 'vegito_purple', tags: ['qualità', 'lungo'], line: 'Disappear in the grind. Let the splits do the talking.' },
    { who: 'Vegeta', s: 'db', icon: '👑', tags: ['qualità'], line: 'Pride isn\'t starting fast. It\'s the last rep matching the first.' },
    { who: 'Vegeta', s: 'db', icon: '👑', tags: ['gara', 'lungo'], line: 'At 30K your legs don\'t get a vote.' },
    { who: 'Gohan', s: 'db', icon: '📘', tags: ['facile', 'riposo'], line: 'The hidden power shows up when it matters. Today, keep it hidden. Run easy.' },
    { who: 'Piccolo', s: 'db', icon: '🟢', tags: ['facile', 'lungo'], line: 'Discipline is running the boring miles like they matter. They do.' },
    // One Piece
    { who: 'Luffy', s: 'op', icon: '🏴‍☠️', img: 'luffy', tags: ['gara', 'riposo'], line: 'Race day is the treasure. Go take it.' },
    { who: 'Luffy', s: 'op', icon: '🏴‍☠️', img: 'luffy', tags: ['facile', 'lungo'], line: 'Be grateful for the legs, the road, the chance. Then go use them.' },
    { who: 'Zoro', s: 'op', icon: '⚔️', tags: ['lungo', 'qualità'], line: 'Every hard mile sharpens the blade.' },
    { who: 'Zoro', s: 'op', icon: '⚔️', tags: ['gara'], line: 'It hurts at 35K. You promised anyway.' },
    { who: 'Sanji', s: 'op', icon: '🍳', tags: ['riposo', 'lungo'], line: 'Nobody sets sail on an empty stomach. Carbs in. Every time.' },
    // Naruto
    { who: 'Naruto', s: 'na', icon: '🍥', tags: ['gara', 'lungo'], line: 'Never giving up isn\'t a slogan. It\'s a pace.' },
    { who: 'Naruto', s: 'na', icon: '🍥', tags: ['qualità'], line: 'A thousand bad reps buy you the one that clicks.' },
    { who: 'Rock Lee', s: 'na', icon: '🔥', img: 'rocklee', tags: ['qualità', 'facile', 'lungo'], line: 'No talent? Fine. Wrap your hands and outwork everyone.' },
    { who: 'Might Guy', s: 'na', icon: '💚', tags: ['qualità', 'gara'], line: 'Open every gate. Leave nothing in the tank on the last rep.' },
    { who: 'Kakashi', s: 'na', icon: '📖', tags: ['riposo', 'facile'], line: 'A smart ninja knows when not to fight. Today\'s rest wins November 8.' },
    { who: 'Sasuke', s: 'na', icon: '🌀', tags: ['qualità'], line: 'Pace. Breath. Nothing else exists.' },
    // Vinland Saga
    { who: 'Thorfinn', s: 'vs', icon: '🌾', tags: ['lungo', 'facile'], line: 'Real strength is plowing the field every day, when nobody\'s watching.' },
    { who: 'Thorfinn', s: 'vs', icon: '🌾', tags: ['gara'], line: 'You have nothing to prove. Run for what you\'ve built.' },
    { who: 'Thors', s: 'vs', icon: '🛡️', tags: ['riposo', 'facile'], line: 'A true warrior doesn\'t need a sword every day. Knowing when to stop is strength.' },
    { who: 'Askeladd', s: 'vs', icon: '🗡️', tags: ['gara', 'qualità'], line: 'The one with a plan wins. First 5K with your head, not your ego.' },
    // Vagabond
    { who: 'Musashi', s: 'vg', icon: '🗻', img: 'musashi_ink', tags: ['lungo', 'facile', 'riposo'], line: 'The way has no end. Every calm step is already the way.' },
    { who: 'Musashi', s: 'vg', icon: '🗻', img: 'musashi_pray', tags: ['gara', 'riposo'], line: 'Forget the bad run. Forgive the slow mile. Bring only the next step.' },
    { who: 'Kojiro', s: 'vg', icon: '🌊', tags: ['qualità', 'facile'], line: 'Don\'t think the perfect stride. Repeat it until it\'s yours.' },
    { who: 'Takuan', s: 'vg', icon: '🍃', tags: ['riposo'], line: 'Still water reflects the moon. A rested mind sees the race clearly.' },
    // Hunter x Hunter
    { who: 'Gon', s: 'hh', icon: '🎣', img: 'gon', tags: ['facile', 'lungo', 'riposo'], line: 'Consistency beats intensity. Always.' },
    { who: 'Gon', s: 'hh', icon: '🎣', img: 'gon', tags: ['gara'], line: 'Want it badly enough and the road gets shorter.' },
    { who: 'Killua', s: 'hh', icon: '⚡', tags: ['qualità'], line: 'Speed without control is just noise. Hit your splits.' },
    { who: 'Netero', s: 'hh', icon: '🙏', tags: ['facile', 'riposo'], line: 'Ten thousand simple reps. That\'s what greatness looks like.' },
    { who: 'Kurapika', s: 'hh', icon: '⛓️', tags: ['gara', 'qualità'], line: 'Race pace is a vow. Don\'t break it in the first 10K.' },
    // Haikyu
    { who: 'Hinata', s: 'hq', icon: '🏐', tags: ['gara', 'qualità'], line: 'You\'re not the biggest. Jump higher anyway.' },
    { who: 'Kageyama', s: 'hq', icon: '👑', tags: ['qualità', 'facile'], line: 'The right pace today is the plan\'s pace. Not one second faster.' },
    { who: 'Bokuto', s: 'hq', icon: '🦉', tags: ['gara', 'lungo'], line: 'Bad days are part of the team. Next K: ace mode.' },
    { who: 'Oikawa', s: 'hq', icon: '🌟', tags: ['qualità', 'riposo'], line: 'Talent is trained. Analyze, recover, repeat.' },
    { who: 'Kenma', s: 'hq', icon: '🎮', tags: ['riposo', 'facile'], line: 'Saving energy is strategy. Easy level today, final boss on November 8.' },
    // Hajime no Ippo (bonus)
    { who: 'Ippo', s: 'ip', icon: '🥊', img: 'ippo', tags: ['gara', 'lungo'], line: 'We have dreams to chase. Every mile you\'ve run is holding you up.' },
  ];

  // citazioni reali di atleti e persone famose, solo con attribuzione solida
  const LEGENDS = [
    { q: 'No human is limited.', by: 'Eliud Kipchoge', role: 'first marathon under 2 hours', tags: ['gara', 'qualità', 'lungo'] },
    { q: 'Only the disciplined ones in life are free. If you are undisciplined, you are a slave to your moods and your passions.', by: 'Eliud Kipchoge', role: 'two-time Olympic marathon champion', tags: ['facile', 'riposo', 'qualità'] },
    { q: 'If you want to run, run a mile. If you want to experience a different life, run a marathon.', by: 'Emil Zátopek', role: '5,000 m, 10,000 m and marathon gold, Helsinki 1952', tags: ['gara', 'lungo'] },
    { q: 'To give anything less than your best is to sacrifice the gift.', by: 'Steve Prefontaine', role: 'American distance legend', tags: ['qualità', 'gara'] },
    { q: 'I hated every minute of training, but I said, don’t quit. Suffer now and live the rest of your life as a champion.', by: 'Muhammad Ali', role: 'three-time heavyweight champion', tags: ['qualità', 'lungo'] },
    { q: 'Run when you can, walk if you have to, crawl if you must; just never give up.', by: 'Dean Karnazes', role: 'ultramarathoner', tags: ['lungo', 'gara'] },
    { q: 'I’ve failed over and over and over again in my life. And that is why I succeed.', by: 'Michael Jordan', role: 'six-time NBA champion', tags: ['facile', 'riposo', 'qualità'] },
    { q: 'The miracle isn’t that I finished. The miracle is that I had the courage to start.', by: 'John Bingham', role: 'runner and writer', tags: ['gara', 'riposo'] },
    { q: 'If you are losing faith in human nature, go out and watch a marathon.', by: 'Kathrine Switzer', role: 'first woman to run Boston as a registered entrant', tags: ['gara', 'riposo'] },
    { q: 'If you have a body, you are an athlete.', by: 'Bill Bowerman', role: 'coach, Nike co-founder', tags: ['facile', 'riposo'] },
    { q: 'The man who can drive himself further once the effort gets painful is the man who will win.', by: 'Roger Bannister', role: 'first sub-4-minute mile', tags: ['qualità', 'gara', 'lungo'] },
  ];

  const seedOf = (str) => [...str].reduce((h, c) => (h * 31 + c.charCodeAt(0)) >>> 0, 7);
  const hasImg = (c) => c.img && IMG[c.img];

  function pick(type, day, offset) {
    const pool = CREW.filter((c) => c.tags.includes(type));
    // i personaggi con immagine compaiono il doppio delle volte
    const list = (pool.length ? pool : CREW).flatMap((c) => (hasImg(c) ? [c, c] : [c]));
    return list[(seedOf(day) + offset) % list.length];
  }

  // immagine a tre pannelli obliqui ("spaccato" da tavola manga) oppure badge neon se manca
  function panel(c, cls) {
    const se = SERIES[c.s];
    const box = el('div', cls);
    box.style.setProperty('--ck', se.color);
    if (hasImg(c)) {
      for (let i = 0; i < 3; i++) {
        const sl = el('div', `ck-slice ck-slice-${i}`);
        sl.style.backgroundImage = `url("${IMG[c.img]}")`;
        box.append(sl);
      }
      box.append(el('div', 'ck-speed'), el('div', 'ck-tone'));
    } else {
      const b = el('div', 'ck-badge');
      b.append(el('span', 'ck-icon', c.icon), el('span', 'ck-ini', c.who.split(' ').map((w) => w[0]).join('').slice(0, 2)));
      box.append(b, el('div', 'ck-speed'));
    }
    return box;
  }

  function strip(current) {
    const seen = new Set();
    const items = CREW.filter((c) => hasImg(c) && !seen.has(c.img) && seen.add(c.img));
    const row = el('div', 'ck-strip');
    row.setAttribute('role', 'list');
    items.forEach((c) => {
      const b = el('button', 'ck-thumb' + (current && current.img === c.img ? ' sel' : ''));
      b.setAttribute('role', 'listitem');
      b.setAttribute('aria-label', `${c.who}, ${SERIES[c.s].name}`);
      b.style.setProperty('--ck', SERIES[c.s].color);
      const im = el('span', 'ck-thumb-img'); im.style.backgroundImage = `url("${IMG[c.img]}")`;
      b.append(im, el('span', 'ck-thumb-name', c.who));
      b.addEventListener('click', () => { S.caricaPick = CREW.indexOf(c); drawAll(); });
      row.append(b);
    });
    return row;
  }

  function render(host, withStrip) {
    if (!host) return;
    const p = dash.data('goal_plan'), g = dash.data('goals');
    const today = p.status === 'ok' ? p.data.find((r) => r.status === 'oggi') : null;
    const goal = g.status === 'ok' ? g.data.find((r) => r.status === 'attivo') : null;
    const type = today ? today.type : 'facile';
    const day = today ? today.date : new Date().toISOString().slice(0, 10);
    const c = S.caricaPick != null ? CREW[S.caricaPick] : pick(type, day, S.caricaOffset);
    const se = SERIES[c.s];

    const hero = el('section', 'ck-hero' + (hasImg(c) ? '' : ' ck-noimg'));
    hero.style.setProperty('--ck', se.color);
    hero.setAttribute('aria-label', 'La carica di oggi');
    const body = el('div', 'ck-body');
    const kicker = el('div', 'ck-kicker');
    kicker.append(el('span', 'ck-dot'), 'La carica di oggi', el('span', 'ck-series', se.name));
    const name = el('h2', 'ck-name', c.who);
    const q = el('blockquote', 'ck-quote');
    q.append(el('span', 'ck-qmark', '“'), el('span', 'ck-qtext', c.line));
    const ctx = el('div', 'ck-ctx');
    if (today) {
      const t = el('span', 'ck-pill');
      t.append('Oggi ', markEl(el('b', null, today.title), 'goal_plan', 'title', 'date=' + today.date));
      ctx.append(t);
    }
    if (goal) {
      const t = el('span', 'ck-pill ck-pill-goal');
      t.append(markEl(el('b', null, String(goal.days_to)), 'goals', 'days_to', 'id=' + goal.id), ' giorni a ',
        markEl(el('span', null, goal.name), 'goals', 'name', 'id=' + goal.id));
      ctx.append(t);
    }
    const foot = el('div', 'ck-foot');
    const btn = el('button', 'ck-btn', 'Un’altra carica ↻');
    btn.addEventListener('click', () => { S.caricaPick = null; S.caricaOffset += 1; drawAll(); });
    foot.append(btn, el('span', 'ck-note', 'frase originale nello spirito del personaggio'));
    body.append(kicker, name, q, ctx, foot);
    hero.append(panel(c, 'ck-art'), body);

    // fascia "Legends": una citazione vera al giorno, legata al tipo di allenamento
    const lp = LEGENDS.filter((x) => x.tags.includes(type));
    const L = (lp.length ? lp : LEGENDS)[(seedOf(day + 'L') + S.caricaOffset) % (lp.length || LEGENDS.length)];
    const leg = el('figure', 'ck-legend');
    leg.style.setProperty('--ck', se.color);
    const lq = el('blockquote', 'ck-legend-q', L.q);
    const cap = el('figcaption', 'ck-legend-by');
    cap.append(el('span', 'ck-legend-tag', 'Legends'), el('b', null, L.by), el('span', null, L.role));
    leg.append(lq, cap);
    host.replaceChildren(hero, leg, ...(withStrip ? [strip(c)] : []));
  }

  function drawAll() {
    render(document.getElementById('carica-oggi'), true);
    render(document.getElementById('carica-obiettivo'), true);
  }
  const base = window.gxDraw;
  window.gxDraw = () => { base(); drawAll(); };
  dash.onData(drawAll);
})();
