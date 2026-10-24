// ============================================================== Icone neon
// Set minimale a tratto sottile (24x24, currentColor). Un osservatore aggiunge l'icona a schede,
// titoli, sezioni del voto e statistiche appena compaiono: i file di disegno non vanno toccati.
// Le icone non hanno testo, quindi non cambiano i valori citati (data-source).
(() => {
  const P = {
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/>',
    target: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.2"/>',
    pulse: '<path d="M2 12h4l2.5-5 4 10 2.5-5H22"/>',
    heart: '<path d="M12 20s-7.5-4.6-7.5-10.2A4.3 4.3 0 0 1 12 7.2a4.3 4.3 0 0 1 7.5 2.6C19.5 15.4 12 20 12 20z"/>',
    bolt: '<path d="M13 2.5 4.5 14H11l-1 7.5L18.5 10H12z"/>',
    trend: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
    run: '<circle cx="15" cy="4.5" r="1.8"/><path d="M13.5 8.5 10 11.5l2.5 3-2 6.5"/><path d="M10 11.5 6.5 10.5M13.5 8.5l2.8 2.8 3.2.4M12.5 14.5l4 1.5.8 4"/>',
    bike: '<circle cx="5.5" cy="16.5" r="3.5"/><circle cx="18.5" cy="16.5" r="3.5"/><path d="M5.5 16.5 9 9h6l3.5 7.5M9 9l3.5 7.5M12.5 16.5 15 9M7.5 6h3"/>',
    swim: '<circle cx="16.5" cy="6.5" r="1.8"/><path d="M5 13l5-5 4 3 4-1"/><path d="M2 17.5c2 0 2-1.5 4-1.5s2 1.5 4 1.5 2-1.5 4-1.5 2 1.5 4 1.5 2-1.5 4-1.5"/>',
    dumbbell: '<path d="M6.5 7v10M17.5 7v10M3.5 9.5v5M20.5 9.5v5M6.5 12h11"/>',
    grid: '<rect x="4" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5"/><rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5"/><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5"/>',
    moon: '<path d="M20 14.5A8.2 8.2 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    battery: '<rect x="3" y="7.5" width="16" height="9" rx="2"/><path d="M21.5 10.5v3M7 10.5v3M10.5 10.5v3"/>',
    gauge: '<path d="M4.6 17.5a8.5 8.5 0 1 1 14.8 0"/><path d="M12 13.5l4-4"/><circle cx="12" cy="13.5" r="1"/>',
    wind: '<path d="M3 8.5h11a2.8 2.8 0 1 0-2.8-2.8M3 12.5h15a2.8 2.8 0 1 1-2.8 2.8M3 16.5h7"/>',
    drop: '<path d="M12 3s6 6.5 6 11a6 6 0 0 1-12 0c0-4.5 6-11 6-11z"/>',
    zigzag: '<path d="M2 13l4-6 4 9 4-11 4 8 4-3"/>',
    mountain: '<path d="M3 19.5l6-10 4 6 2.5-3.5 5.5 7.5z"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3.2 2"/>',
    route: '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M8 6h7.5a3 3 0 0 1 0 6h-7a3 3 0 0 0 0 6H16"/>',
    timer: '<circle cx="12" cy="13.5" r="7.5"/><path d="M12 13.5l3-3M10 2.5h4M12 2.5V6"/>',
    flame: '<path d="M12 3c1 3.5 5.5 5.5 5.5 10.5a5.5 5.5 0 0 1-11 0c0-2.5 1.5-4 2.2-5.5 1 1.5 2.3 2.3 2.3 2.3S10.5 6.5 12 3z"/>',
    flag: '<path d="M5.5 21V3.5M5.5 4h11l-2.2 4 2.2 4h-11"/>',
    feet: '<path d="M8 3.5c-1.8 0-2.5 2.6-2.5 4.6s.7 3.6 2.5 3.6 2.5-1.6 2.5-3.6S9.8 3.5 8 3.5zM6 14.5h4v1.8a2 2 0 0 1-4 0zM16 8c-1.8 0-2.5 2.6-2.5 4.6s.7 3.6 2.5 3.6 2.5-1.6 2.5-3.6S17.8 8 16 8zM14 19h4v.2a2 2 0 0 1-4 0z"/>',
    shoe: '<path d="M3.5 16.5h15.5a2 2 0 0 0 0-4l-5-1.2-2-3.8H7L3.5 12.5z"/><path d="M3 20.5h18"/>',
    updown: '<path d="M12 3v18M8 7l4-4 4 4M8 17l4 4 4-4"/>',
    shield: '<path d="M12 3l7.5 3v6c0 4.8-3.3 7.9-7.5 9-4.2-1.1-7.5-4.2-7.5-9V6z"/><path d="M8.7 12l2.3 2.3 4.4-4.6"/>',
    layers: '<path d="M12 3.5l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
    repeat: '<path d="M17 2.5l3 3-3 3M4 11.5v-2a4 4 0 0 1 4-4h12M7 21.5l-3-3 3-3M20 12.5v2a4 4 0 0 1-4 4H4"/>',
    bars: '<path d="M5 20v-7M10 20V5M15 20v-9M20 20V8"/>',
    equal: '<path d="M4 7h16M4 12h16M4 17h16"/>',
    pause: '<circle cx="12" cy="12" r="9"/><path d="M10 9v6M14 9v6"/>',
    drift: '<path d="M3 16c3 0 4.5-7 8.5-7s5 4.5 9.5 4.5"/><path d="M3 20h18"/>',
    check: '<circle cx="12" cy="12" r="9"/><path d="M8 12.5l2.7 2.7L16.2 9.5"/>',
    compass: '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    trophy: '<path d="M8 3.5h8V9a4 4 0 0 1-8 0zM8 5.5H5a3 3 0 0 0 3 4M16 5.5h3a3 3 0 0 1-3 4M12 13v4M8 21h8M9.5 17h5"/>',
    calendar: '<rect x="3.5" y="5" width="17" height="15.5" rx="2"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
    list: '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r=".6"/><circle cx="4.5" cy="12" r=".6"/><circle cx="4.5" cy="18" r=".6"/>',
    spark: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 16.5v4M17 18.5h4"/>',
    scale: '<path d="M12 4v16M6.5 20h11M4.5 8h15M6.5 8l-3 6a3 3 0 0 0 6 0zM17.5 8l-3 6a3 3 0 0 0 6 0z"/>',
    lungs: '<path d="M12 4v7l-3 2m3-2 3 2M9 8c-3 0-5 5-5 9 0 2 1 3 3 3s3-1 3-3v-6M15 8c3 0 5 5 5 9 0 2-1 3-3 3s-3-1-3-3v-6"/>',
    ruler: '<path d="M3 17 17 3l4 4L7 21z"/><path d="M7 13l2 2M10 10l2 2M13 7l2 2"/>',
    treadmill: '<path d="M3 15.5h17a2 2 0 0 1 0 4H3a2 2 0 0 1 0-4z"/><path d="M16 15.5l2.5-10H21"/>',
    split: '<path d="M4 20V10M9 20V6M14 20V12M19 20V8"/><path d="M2.5 20h19"/>',
    wave: '<path d="M2 12c2.5-5 5-5 7.5 0s5 5 7.5 0 3.5-4 5-2"/>',
  };
  // [chiave normalizzata del testo, icona, tono]
  const T = {
    // pagine
    oggi: ['sun', 'cyan'], obiettivo: ['target', 'magenta'], recupero: ['heart', 'pink'], allenamenti: ['list', 'lime'], progressi: ['trend', 'violet'],
    // sport e ambienti
    tutti: ['grid'], corsa: ['run', 'lime'], bici: ['bike', 'cyan'], nuoto: ['swim', 'violet'], altro: ['dumbbell', 'amber'],
    outdoor: ['sun', 'amber'], 'tapis roulant': ['treadmill', 'violet'],
    // Oggi
    'allenamento di oggi': ['bolt', 'cyan'], 'indice di recupero': ['heart', 'pink'], 'carico di oggi': ['flame', 'amber'],
    'recupero, ultimi 60 giorni': ['pulse', 'cyan'], hrv: ['pulse', 'cyan'], sonno: ['moon', 'violet'], 'fc a riposo': ['heart', 'pink'],
    'body battery': ['battery', 'lime'], stress: ['zigzag', 'amber'],
    "esecuzione dellallenamento": ['target', 'magenta'], 'tecnica e tenuta': ['shoe', 'lime'],
    // statistiche
    distanza: ['route', 'cyan'], durata: ['clock', 'cyan'], tempo: ['clock', 'cyan'], passo: ['timer', 'cyan'], 'fc media': ['heart', 'pink'],
    'fc max': ['heart', 'pink'], dislivello: ['mountain', 'lime'], tss: ['flame', 'amber'], cadenza: ['feet', 'lime'], contatto: ['shoe', 'amber'],
    'efficiency factor': ['gauge', 'cyan'], 'vo2max garmin': ['lungs', 'violet'],
    // obiettivo
    'obiettivo attivo': ['target', 'magenta'], 'tempo stimato': ['timer', 'magenta'], 'stima per metodo': ['spark', 'cyan'],
    'la stima giorno per giorno': ['trend', 'cyan'], 'piano fino alla gara': ['calendar', 'cyan'], 'come si e adattato il piano': ['repeat', 'amber'],
    'zone per questo obiettivo': ['compass', 'cyan'],
    'scarico 1': ['layers', 'cyan'], 'scarico 2': ['layers', 'violet'], 'settimana gara': ['flag', 'magenta'], 'voto agli allenamenti svolti': ['check', 'lime'], 'storico obiettivi': ['trophy', 'amber'],
    'velocita critica': ['bolt', 'violet'], vdot: ['gauge', 'magenta'], riegel: ['trend', 'amber'], durability: ['shield', 'lime'],
    // recupero
    'come stai assorbendo il carico': ['heart', 'pink'], 'voto di recupero per settimana': ['bars', 'cyan'], 'metriche giornaliere': ['calendar', 'cyan'],
    'sistema nervoso autonomo': ['pulse', 'cyan'], 'segnali respiratori ed energia': ['wind', 'lime'], carico: ['flame', 'amber'],
    'hrv notturna': ['pulse', 'cyan'], 'variabilita hrv': ['wave', 'amber'], 'durata vs fabbisogno': ['moon', 'violet'], 'sleep score': ['moon', 'violet'],
    'sonno profondo e rem': ['layers', 'violet'], 'orario di addormentamento': ['clock', 'violet'], 'respiro nel sonno': ['wind', 'lime'],
    'spo2 nel sonno': ['drop', 'cyan'], 'body battery ricaricata': ['battery', 'lime'], 'carico acuto vs cronico': ['flame', 'amber'],
    'rapporto acuto:cronico': ['scale', 'amber'], 'forma': ['wave', 'lime'], 'indice di recupero giornaliero': ['heart', 'pink'],
    'quantita di sonno': ['moon', 'violet'], 'qualita del sonno': ['layers', 'violet'], 'regolarita del sonno': ['clock', 'violet'],
    'stress ed energia': ['zigzag', 'amber'], 'equilibrio del carico': ['scale', 'amber'],
    // allenamenti e progressi
    'allenamenti valutati': ['list', 'lime'], 'voto per componente': ['bars', 'cyan'], 'report corsa': ['run', 'lime'], 'voto per sezione': ['bars', 'cyan'],
    'frequenza cardiaca': ['heart', 'pink'], altimetria: ['mountain', 'lime'], 'dinamiche di corsa': ['shoe', 'lime'], 'split per km': ['split', 'cyan'],
    'oscillazione verticale': ['updown', 'violet'], 'rapporto verticale': ['updown', 'cyan'], 'lunghezza del passo': ['ruler', 'magenta'],
    'ftp e potenza in bici': ['bolt', 'amber'], 'progressi corsa': ['trend', 'lime'], 'passo a parita di frequenza cardiaca': ['heart', 'pink'],
    'dinamiche a parita di passo': ['shoe', 'lime'], 'deriva cardiaca': ['drift', 'amber'], 'vo2max stimato': ['lungs', 'violet'],
    'volume settimanale': ['bars', 'cyan'], 'voti per sezione nel tempo': ['trend', 'cyan'],
    // sezioni del voto tecnico
    'controllo intensita': ['gauge', 'magenta'], 'efficienza aerobica': ['heart', 'pink'], 'gestione del ritmo': ['timer', 'cyan'],
    'contatto al suolo': ['shoe', 'amber'], 'rimbalzo verticale': ['updown', 'violet'], 'resistenza alla fatica': ['shield', 'lime'],
    'aderenza zone': ['gauge', 'magenta'], 'aderenza target workout': ['target', 'magenta'], 'decoupling pw:hr': ['drift', 'amber'],
    'bilanciamento dx/sx': ['scale', 'cyan'], 'efficienza vs storico': ['trend', 'lime'], 'passo vs css': ['timer', 'cyan'],
    'passo vs storico': ['trend', 'lime'], 'costanza swolf': ['wave', 'violet'], 'costanza frequenza bracciata': ['repeat', 'violet'],
    'stabilita passo': ['equal', 'cyan'], tenuta: ['shield', 'lime'],
    // voci del voto del preparatore
    'fc sotto la soglia aerobica': ['heart', 'pink'], 'passo nel range facile': ['timer', 'cyan'], 'durata rispettata': ['clock', 'cyan'],
    'passo delle ripetute': ['timer', 'magenta'], 'regolarita tra le ripetute': ['equal', 'cyan'], 'fc coerente con lo sforzo': ['heart', 'pink'],
    'recuperi rispettati': ['pause', 'violet'], 'volume di qualita completato': ['layers', 'lime'], 'durata/distanza': ['route', 'cyan'],
    'tratti a passo gara': ['flag', 'magenta'], 'tenuta del passo nel finale': ['flag', 'lime'], regolarita: ['equal', 'cyan'],
    'risultato vs stima': ['target', 'magenta'],
  };
  const key = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/['’]/g, '')
    .split(/[·(]/)[0].replace(/\s+/g, ' ').trim();
  const SVGNS = 'http://www.w3.org/2000/svg';

  function icon(name, tone) {
    const svg = document.createElementNS(SVGNS, 'svg');
    svg.setAttribute('viewBox', '0 0 24 24');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('class', 'nx-ic' + (tone ? ' nx-ic-' + tone : ''));
    svg.innerHTML = P[name] || '';          // markup costante del set, mai dati
    svg.querySelectorAll('path, circle, rect').forEach((e) => e.setAttribute('pathLength', '1'));
    return svg;
  }

  // dove mettere l'icona: [selettore, elemento in cui inserirla]
  const SPOTS = [
    ['[data-icon]', (e) => e],
    ['.nx h3', (e) => e],
    ['.gx-card > h2', (e) => e],
    ['.nx-eyebrow', (e) => e],
    ['.nx-sec-name', (e) => e],
    ['.gl-part-name > b:first-child', (e) => e.parentElement],
    ['.nx-stat > span:first-child', (e) => e],
    ['.gx-tile-name', (e) => e],
    ['.gx-chip[data-sport], .nx-chip[data-runenv]', (e) => e],
  ];

  function decorate(root) {
    for (const [sel, host] of SPOTS) {
      root.querySelectorAll(sel).forEach((e) => {
        const h = host(e);
        if (!h || h.querySelector(':scope > .nx-ic') || h.closest('.nx-ic')) return;
        const hit = e.dataset.icon ? [e.dataset.icon, e.dataset.iconTone] : T[key(e.textContent)];
        if (!hit || !P[hit[0]]) return;
        h.prepend(icon(hit[0], hit[1]));
        h.classList.add('nx-has-ic');
      });
    }
  }

  const root = document.querySelector('.gx') || document.body;
  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; decorate(root); });
  }).observe(root, { childList: true, subtree: true, characterData: true });
  decorate(root);
  window.nxIcon = icon;
})();
