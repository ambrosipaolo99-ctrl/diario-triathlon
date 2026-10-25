// ============================================================== Glossario: tocca una metrica per sapere cos'e'
// Le etichette con una voce qui sotto diventano toccabili (sottolineatura tratteggiata); il riquadro si chiude
// toccando altrove. Le chiavi usano la stessa normalizzazione delle icone (window.nxKey).
(() => {
  const G = {
    // ---------------------------------------------------------- corsa
    distanza: 'Chilometri percorsi in movimento, dal GPS (o dal sensore sul tapis roulant).',
    durata: 'Tempo in movimento: le soste non contano.',
    tempo: 'Tempo in movimento: le soste non contano.',
    passo: 'Minuti per chilometro sui tratti in movimento. Più basso vuol dire più veloce.',
    'fc media': 'Frequenza cardiaca media della corsa, in battiti al minuto.',
    'fc max': 'Il battito più alto registrato durante la corsa.',
    dislivello: "Metri di salita totali, presi sempre da Strava: mai dall'orologio, che anche in piano sbaglia.",
    tss: "Training Stress Score: quanto ha pesato l'allenamento, unendo durata e intensità. 100 ≈ un'ora alla soglia.",
    cadenza: 'Passi al minuto, contando entrambi i piedi. Sale con la velocità; più alta di solito significa appoggi più leggeri.',
    contatto: 'Millisecondi in cui il piede resta a terra a ogni passo. A parità di velocità, più breve = corsa più reattiva.',
    'contatto al suolo': 'Tempo del piede a terra a ogni passo e bilanciamento sinistro/destro. A parità di velocità, più breve e più simmetrico è meglio.',
    'efficiency factor': "Metri al minuto ottenuti per ogni battito. Se sale nel tempo a parità di sforzo, il motore aerobico migliora.",
    'vo2max garmin': 'Stima Garmin del massimo consumo di ossigeno (ml/kg/min): il tuo potenziale aerobico.',
    'vo2max stimato': 'Stima Garmin del massimo consumo di ossigeno (ml/kg/min): il tuo potenziale aerobico.',
    'controllo intensita': "Quanto sei rimasto nelle zone (FC o target) giuste per quel tipo di allenamento.",
    'efficienza aerobica': 'Deriva cardiaca ed Efficiency Factor rispetto alle tue corse simili: se il cuore non sale, la base aerobica è solida.',
    'gestione del ritmo': 'Costanza del passo tra i giri e tra prima e seconda metà; nelle ripetute, quanto sono uguali tra loro.',
    'rimbalzo verticale': "Quanto sali e scendi rispetto alla lunghezza del passo. Meno è meglio: l'energia va in avanti, non in alto.",
    'resistenza alla fatica': "Quanto cambiano cadenza, contatto, passo e costo cardiaco nell'ultimo terzo rispetto al primo: la tenuta del gesto.",
    'oscillazione verticale': 'Centimetri di su e giù del busto a ogni passo.',
    'rapporto verticale': 'Oscillazione verticale divisa per la lunghezza del passo. Più basso = corsa più economica.',
    'lunghezza del passo': 'Distanza tra due appoggi consecutivi, in metri.',
    'deriva cardiaca': 'Quanto peggiora il rapporto passo/battito nella seconda metà. Sotto il 5% la base aerobica regge bene.',
    'frequenza cardiaca': 'Battiti al minuto lungo il percorso.',
    'split per km': 'Passo di ogni chilometro; il colore indica la FC (dal ciano, bassa, al magenta, alta).',
    altimetria: "Profilo della quota; il dislivello totale è sempre quello di Strava.",
    'passo a parita di frequenza cardiaca': 'A che passo corri con lo stesso battito: se diventa più veloce nel tempo, sei più in forma.',
    'dinamiche a parita di passo': 'Cadenza, contatto e oscillazione allo stesso passo: se migliorano, il gesto è più economico.',
    'volume settimanale': 'Chilometri di corsa per settimana, outdoor e tapis roulant insieme.',
    // ---------------------------------------------------------- recupero
    'indice di recupero': 'Sintesi 0-100 di HRV, sonno, FC a riposo, Body Battery e stress, confrontati con i tuoi ultimi 60 giorni.',
    hrv: 'Variabilità del battito nel sonno. Più alta della tua media = sistema nervoso recuperato.',
    'hrv notturna': 'Variabilità del battito nel sonno. Più alta della tua media = sistema nervoso recuperato.',
    'variabilita hrv': "Quanto oscilla l'HRV da un giorno all'altro (7 giorni). Sopra il 6% il sistema è sotto stress.",
    sonno: 'Punteggio e ore di sonno della notte, rispetto al tuo fabbisogno.',
    'fc a riposo': 'Battito a riposo. Se sale sopra la tua media spesso segnala fatica, stress o un malanno in arrivo.',
    'body battery': "Energia stimata da Garmin (0-100) al risveglio, da HRV, stress e sonno.",
    'body battery ricaricata': 'Punti di energia recuperati durante la notte.',
    stress: 'Stress medio della giornata, misurato da Garmin dalla variabilità del battito.',
    'durata vs fabbisogno': 'Ore dormite rispetto al fabbisogno stimato da Garmin.',
    'sleep score': 'Punteggio Garmin della notte (0-100): durata, fasi e risvegli.',
    'sonno profondo e rem': 'Quota di sonno profondo (recupero fisico) e REM (recupero mentale) sul totale.',
    'orario di addormentamento': "Ora in cui ti addormenti: più è regolare, meglio recuperi.",
    'respiro nel sonno': "Respiri al minuto nel sonno: un aumento rispetto alla tua base spesso anticipa un'infezione.",
    'spo2 nel sonno': "Saturazione di ossigeno nel sonno (%).",
    'quantita di sonno': 'Ore dormite rispetto al fabbisogno, nella settimana.',
    'qualita del sonno': 'Sleep Score e quota di sonno profondo + REM, nella settimana.',
    'regolarita del sonno': "Quanto è costante l'orario in cui ti addormenti.",
    'stress ed energia': 'Stress diurno e energia recuperata di notte (Body Battery).',
    'equilibrio del carico': 'Rapporto tra carico recente e abituale, e forma (TSB).',
    'segnali respiratori': 'Respiro e SpO2 notturni rispetto alla tua base: spesso cambiano prima di un malanno.',
    // ---------------------------------------------------------- carico
    cronico: "CTL: il carico medio delle ultime 6 settimane circa. È la tua forma di base.",
    acuto: "ATL: il carico medio dell'ultima settimana circa. È la fatica recente.",
    forma: "TSB = cronico − acuto. Negativo: stai accumulando fatica; positivo: sei fresco.",
    'rapporto acuto:cronico': "Carico dell'ultima settimana rispetto alle ultime 6. Tra 0,8 e 1,3 il rischio di sovraccarico è più basso.",
    'carico acuto vs cronico': 'Fatica recente (acuto) e forma di base (cronico); le barre sono il carico di ogni giorno.',
    'carico di oggi': 'Forma, fatica e rapporto tra carico recente e abituale, calcolati dal TSS di tutti gli allenamenti.',
    // ---------------------------------------------------------- voto del preparatore
    'esecuzione dellallenamento': 'Quanto la seduta ha rispettato il piano e gli obiettivi del suo tipo: 70% del voto.',
    'tecnica e tenuta': 'Qualità del gesto: cadenza, contatto, rimbalzo e tenuta con la fatica: 30% del voto.',
    'fc sotto la soglia aerobica': 'Quota di tempo con il battito sotto il tetto della Z2: in un facile dovrebbe essere quasi tutto.',
    'passo nel range facile': 'Se il passo è rimasto nel ritmo facile; in salita conta poco.',
    'durata rispettata': 'Chilometri fatti rispetto a quelli previsti dal piano.',
    'durata/distanza': 'Chilometri fatti rispetto a quelli previsti (o al lungo di riferimento).',
    'passo delle ripetute': 'Quanto le ripetute sono state nel passo obiettivo.',
    'regolarita tra le ripetute': "Quanto le ripetute sono state uguali tra loro.",
    regolarita: 'Quanto sono stati uguali gli split.',
    'fc coerente con lo sforzo': 'Se il battito nei tratti veloci era quello atteso per quel passo.',
    'recuperi rispettati': 'Se le pause tra le ripetute sono durate quanto previsto.',
    'volume di qualita completato': 'Chilometri fatti davvero al passo obiettivo rispetto a quelli previsti.',
    'tratti a passo gara': 'Quanti chilometri al ritmo gara, e con quale battito.',
    'tenuta del passo nel finale': "Quanto rallenti nell'ultimo 20% rispetto alla prima metà.",
    'risultato vs stima': 'Tempo di gara rispetto alla stima della vigilia.',
    // ---------------------------------------------------------- analisi predittive
    prontezza: 'Quanto sei pronto oggi: sistema autonomo (HRV, battito, sonno) × neuromuscolare (test sul telefono).',
    'sistema autonomo': "Recupero 'interno' da HRV (50%), FC a riposo e sonno, rispetto alla tua base.",
    'sistema neuromuscolare': 'Prontezza dei muscoli e dei riflessi: tapping test di 10 s o salto CMJ, confrontati con la tua media.',
    'carico cuore e struttura': 'Quanto lavora il cuore (TRIMP) e quanto lavorano gambe e articolazioni (impatti e discese) negli ultimi 7 giorni, rispetto al tuo storico.',
    cardiovascolare: "Carico per il cuore: minuti in ogni zona di FC pesati per l'intensità (TRIMP).",
    cuore: "Carico per il cuore: minuti in ogni zona di FC pesati per l'intensità (TRIMP).",
    strutturale: 'Carico per gambe e articolazioni: passi × forza di ogni impatto, più alto in discesa e se appoggi in modo asimmetrico.',
    struttura: 'Carico per gambe e articolazioni: passi × forza di ogni impatto, più alto in discesa e se appoggi in modo asimmetrico.',
    'carico della corsa': 'Il peso di questa corsa per cuore e struttura, rispetto alle tue corse degli ultimi 120 giorni.',
    carburante: 'Energia, carboidrati e grassi bruciati, e quanto reintegrare dopo.',
    energia: 'Calorie spese correndo: circa 1 kcal per kg per km.',
    carboidrati: "Grammi di zuccheri bruciati: più alta è l'intensità, più se ne usano.",
    grassi: 'Grammi di grassi bruciati: soprattutto alle andature facili.',
    'glicogeno usato': 'Quota delle scorte di zuccheri nei muscoli e nel fegato consumata (stima ~7 g/kg).',
    'deriva biomeccanica': "Come cambia il gesto con la fatica: cadenza, contatto, oscillazione e simmetria nell'ultimo terzo.",
    'forma verso la gara': 'Modello forma-fatica: proietta il piano fino alla gara e mostra quando sarai più in forma.',
  };
  const SEL = '.nx-stat > span:first-child, .gx-tile-name, .nx-sec-name, .gl-part-name > b, .nx-card-head > h3, .gx-dl dt, '
    + '.px-sys-name, .gx-card > h2';
  const keyOf = (e) => (window.nxKey ? window.nxKey(e.textContent) : (e.textContent || '').toLowerCase().trim());
  const root = document.querySelector('.gx') || document.body;

  function decorate() {
    root.querySelectorAll(SEL).forEach((e) => {
      if (e.classList.contains('nx-gl')) return;
      if (!G[keyOf(e)]) return;
      e.classList.add('nx-gl');
      e.tabIndex = 0;
      e.setAttribute('role', 'button');
      e.setAttribute('aria-haspopup', 'dialog');
    });
  }

  let tip = null;
  const close = () => { if (tip) { tip.remove(); tip = null; } };
  function open(e) {
    close();
    const text = G[keyOf(e)];
    if (!text) return;
    tip = document.createElement('div');
    tip.className = 'nx-gloss';
    tip.setAttribute('role', 'dialog');
    const b = document.createElement('b'); b.textContent = e.textContent.split(/[·(]/)[0].trim();
    const p = document.createElement('p'); p.textContent = text;
    tip.append(b, p);
    document.body.append(tip);
    const r = e.getBoundingClientRect(), vw = document.documentElement.clientWidth, vh = window.innerHeight;
    const w = Math.min(300, vw - 24);
    tip.style.width = w + 'px';
    tip.style.left = Math.max(12, Math.min(vw - w - 12, r.left)) + 'px';
    const below = r.bottom + 8, h = tip.offsetHeight;
    tip.style.top = (below + h > vh - 12 ? Math.max(12, r.top - h - 8) : below) + 'px';
  }

  document.addEventListener('click', (ev) => {
    const e = ev.target.closest && ev.target.closest('.nx-gl');
    if (e) { ev.preventDefault(); ev.stopPropagation(); open(e); return; }
    if (!(tip && tip.contains(ev.target))) close();
  }, true);
  document.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') close();
    if ((ev.key === 'Enter' || ev.key === ' ') && document.activeElement && document.activeElement.classList.contains('nx-gl')) {
      ev.preventDefault(); open(document.activeElement);
    }
  });
  window.addEventListener('scroll', close, { passive: true });
  window.addEventListener('resize', close);

  let queued = false;
  new MutationObserver(() => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; decorate(); });
  }).observe(root, { childList: true, subtree: true });
  decorate();
})();
