// ============================================================== Diario Triathlon, web app
// Fa le veci della dashboard di claude.ai: fornisce `dash` (data, onData, calc, setLink, colors) alle
// pagine, scarica data.bin e lo decifra SUL TELEFONO con la chiave ricavata dalla frase segreta
// (PBKDF2-SHA256 + AES-256-GCM, WebCrypto). La frase non lascia mai il dispositivo; la chiave ricavata
// resta in IndexedDB come CryptoKey non esportabile, finche' non si preme "Blocca".
(() => {
  'use strict';
  if (window.top !== window.self) { document.documentElement.textContent = ''; throw new Error('frame'); }

  const DATA_URL = 'data.bin';
  const MAGIC = 'DTD1';
  const sources = Object.create(null);   // dataset -> righe
  const calcs = Object.create(null);     // id -> {inputs, fn}
  const listeners = [];
  let state = 'loading';                 // loading | ok | error
  let errorMsg = '';
  let version = 0;
  const calcCache = Object.create(null);

  const columnsOf = (rows) => (Array.isArray(rows) && rows.length && typeof rows[0] === 'object' ? Object.keys(rows[0]) : []);
  const rank = { error: 4, missing: 3, loading: 2, ok: 1 };

  function data(id) {
    if (calcs[id]) {
      const ins = calcs[id].inputs.map(data);
      const worst = ins.reduce((w, d) => (rank[d.status] > rank[w] ? d.status : w), 'ok');
      if (worst !== 'ok') return { status: worst === 'missing' ? 'error' : worst, data: [], columns: [], meta: [], refreshing: false, message: '' };
      const c = calcCache[id];
      if (c && c.v === version) return c.r;
      let r;
      try {
        const out = calcs[id].fn(...ins.map((d) => d.data));
        r = { status: 'ok', data: out, columns: columnsOf(out), meta: [], refreshing: false, message: '' };
      } catch (e) {
        console.error('calc', id, e);
        r = { status: 'error', data: [], columns: [], meta: [], refreshing: false, message: String(e) };
      }
      calcCache[id] = { v: version, r };
      return r;
    }
    if (state !== 'ok') return { status: state, data: [], columns: [], meta: [], refreshing: false, message: errorMsg };
    if (!(id in sources)) return { status: 'missing', data: [], columns: [], meta: [], refreshing: false, message: '' };
    const rows = sources[id];
    return { status: 'ok', data: rows, columns: columnsOf(rows), meta: [], refreshing: false, message: '' };
  }

  function emit() {
    version += 1;
    for (const fn of listeners) {
      try { fn(); } catch (e) { console.error('onData', e); }
    }
  }

  window.dash = {
    data,
    onData(fn) { listeners.push(fn); try { fn(); } catch (e) { console.error('onData', e); } },
    calc(id, spec) { calcs[id] = { inputs: spec.inputs || [], fn: spec.fn }; },
    loader() {},
    setLink(name) { try { history.replaceState(null, '', '#' + encodeURIComponent(name)); } catch (e) { /* ignorato */ } },
    refresh() {},
    params() { return {}; }, setParams() {}, resetParams() {},
    colors: ['#22e5ff', '#ff3df2', '#b4ff39', '#ffb22e', '#9b7bff', '#ff4d7d', '#5ef0c4', '#8391b8'],
  };
  window.CK_IMG = {};   // immagini della card "La carica": arrivano dentro il pacchetto cifrato

  // ridisegno quando cambia la larghezza (rotazione del telefono, finestra)
  let lastW = 0, raf = 0;
  const watchWidth = () => {
    const w = document.getElementById('dash-root')?.clientWidth || 0;
    if (w && Math.abs(w - lastW) > 1) { lastW = w; cancelAnimationFrame(raf); raf = requestAnimationFrame(emit); }
  };
  window.addEventListener('resize', watchWidth);
  window.addEventListener('orientationchange', () => setTimeout(watchWidth, 250));

  // ------------------------------------------------------------ chiave in IndexedDB
  const IDB = 'diario-triathlon', STORE = 'keys';
  const idb = () => new Promise((res, rej) => {
    const r = indexedDB.open(IDB, 1);
    r.onupgradeneeded = () => r.result.createObjectStore(STORE);
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  const idbDo = async (mode, fn) => {
    const db = await idb();
    return new Promise((res, rej) => {
      const tx = db.transaction(STORE, mode);
      const req = fn(tx.objectStore(STORE));
      tx.oncomplete = () => res(req && req.result);
      tx.onerror = () => rej(tx.error);
    });
  };
  const getKey = (id) => idbDo('readonly', (s) => s.get(id)).catch(() => null);
  const putKey = (id, k) => idbDo('readwrite', (s) => s.put(k, id)).catch(() => null);
  const clearKeys = () => idbDo('readwrite', (s) => s.clear()).catch(() => null);

  // ------------------------------------------------------------ decifratura
  const hex = (b) => Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  function parse(buf) {
    const u = new Uint8Array(buf);
    if (u.length < 52 || String.fromCharCode(...u.slice(0, 4)) !== MAGIC) throw new Error('formato');
    const iters = new DataView(buf, 20, 4).getUint32(0);
    return { header: u.slice(0, 36), salt: u.slice(4, 20), iters, nonce: u.slice(24, 36), ct: u.slice(36) };
  }
  async function derive(passphrase, salt, iters) {
    const base = await crypto.subtle.importKey('raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveKey']);
    return crypto.subtle.deriveKey({ name: 'PBKDF2', hash: 'SHA-256', salt, iterations: iters }, base,
      { name: 'AES-GCM', length: 256 }, false, ['decrypt']);
  }
  async function open(p, key) {
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: p.nonce, additionalData: p.header }, key, p.ct);
    const stream = new Blob([plain]).stream().pipeThrough(new DecompressionStream('gzip'));
    return JSON.parse(await new Response(stream).text());
  }

  // ------------------------------------------------------------ interfaccia
  const $ = (id) => document.getElementById(id);
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const fmtTime = (iso) => { try { return new Date(iso).toLocaleString('it-IT', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }); } catch (e) { return iso; } };

  function showLock(msg) {
    $('lock').hidden = false;
    $('app').hidden = true;
    $('lock-msg').textContent = msg || '';
    setTimeout(() => $('lock-pass').focus(), 50);
  }

  function install(bundle) {
    for (const k of Object.keys(sources)) delete sources[k];
    for (const [k, v] of Object.entries(bundle)) if (!k.startsWith('_')) sources[k] = v;
    Object.assign(window.CK_IMG, bundle._carica_img || {});
    state = 'ok';
    $('lock').hidden = true;
    $('app').hidden = false;
    footer(bundle._meta && bundle._meta[0], bundle._sync_log || []);
    lastW = $('dash-root').clientWidth;
    emit();
  }

  function footer(meta, log) {
    const f = $('app-foot');
    f.replaceChildren();
    if (meta) {
      const line = el('p', 'app-foot-line');
      line.append('Aggiornato ', el('b', null, fmtTime(meta.generated_at)));
      const bad = (meta.steps || []).filter((s) => !s.ok);
      if (bad.length) {
        const w = el('div', 'app-warn');
        w.append(el('b', null, 'Ultima sincronizzazione con errori: '), bad.map((s) => s.step).join(', '));
        f.append(w);
      }
      const notes = (meta.steps || []).filter((s) => s.ok && s.note);
      notes.forEach((s) => f.append(el('div', 'app-note', `${s.step}: ${s.note}`)));
      f.append(line);
    }
    const tools = el('div', 'app-foot-tools');
    const lock = el('button', 'app-btn', 'Blocca');
    lock.addEventListener('click', async () => { await clearKeys(); location.reload(); });
    const det = el('details', 'app-log');
    det.append(el('summary', null, 'Registro sincronizzazione'), el('pre', null, log.join('\n')));
    tools.append(lock);
    f.append(tools, det);
  }

  let pending = null;   // dati cifrati in attesa della frase

  async function start() {
    let buf;
    try {
      const r = await fetch(DATA_URL, { cache: 'no-cache' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      buf = await r.arrayBuffer();
    } catch (e) {
      state = 'error'; errorMsg = 'Dati non raggiungibili';
      showLock('Dati non raggiungibili: controlla la connessione.');
      return;
    }
    let p;
    try { p = parse(buf); } catch (e) { showLock('File dei dati non valido.'); return; }
    if (typeof DecompressionStream === 'undefined') { showLock('Serve iOS 16.4 o successivo (o un browser aggiornato).'); return; }
    pending = p;
    const id = hex(p.salt);
    const key = await getKey(id);
    if (key) {
      try { install(await open(p, key)); return; } catch (e) { await clearKeys(); }
    }
    showLock('');
  }

  async function unlock(ev) {
    ev.preventDefault();
    const pass = $('lock-pass').value;
    if (!pending || !pass) return;
    const btn = $('lock-go');
    btn.disabled = true; $('lock-msg').textContent = 'Verifica…';
    try {
      const key = await derive(pass, pending.salt, pending.iters);
      const bundle = await open(pending, key);
      await putKey(hex(pending.salt), key);
      $('lock-pass').value = '';
      install(bundle);
    } catch (e) {
      $('lock-msg').textContent = 'Frase non corretta.';
    } finally {
      btn.disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    $('lock-form').addEventListener('submit', unlock);
    start();
  });

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
  }
})();
