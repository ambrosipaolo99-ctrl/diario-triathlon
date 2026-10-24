// ---------------------------------------------------------------- calcoli
dash.calc('ftp_est', {
  inputs: ['activities'],
  title: 'FTP stimata (95% best 20\' su 90 gg)',
  description: 'Per ogni uscita in bici con potenza: 95% del miglior 20 minuti tra quella data e i 90 giorni precedenti.',
  fn: (activities) => {
    const rides = activities.filter((a) => a.sport === 'bike' && !a.duplicate && a.best_20min)
      .map((a) => ({ id: a.id, date: a.date, t: Date.parse(a.date), b: a.best_20min })).sort((a, b) => a.t - b.t);
    return rides.map((r) => ({ id: r.id, date: r.date,
      ftp_est: Math.round(0.95 * Math.max(...rides.filter((q) => q.t <= r.t && r.t - q.t <= 90 * 864e5).map((q) => q.b))) }));
  },
});
