# Diario Triathlon

Dashboard di allenamento e recupero per iPhone (web app installabile), alimentata dai dati Garmin Connect.
Ogni notte GitHub Actions scarica i dati, calcola recupero, voti, stima gara e piano, e pubblica la
dashboard **cifrata** su GitHub Pages. Si apre solo con la frase segreta del proprietario.

## Sicurezza

Il repository è pubblico (GitHub Pages gratuito lo richiede), quindi **nulla qui è leggibile**:

| Cosa | Dove | Protezione |
|---|---|---|
| Dati della dashboard | `data.bin` sul sito | AES-256-GCM; chiave da frase segreta (PBKDF2-SHA256, 600.000 iterazioni) decifrata solo sul telefono |
| Database, obiettivi, token Garmin | release `state` | AES-256-GCM con chiave casuale (`STATE_KEY`) che esiste solo nei segreti di GitHub |
| Password Garmin | segreto `GARMIN_PASSWORD` | usata solo al primo accesso, poi va cancellata |
| Log delle esecuzioni | pubblici | solo "OK/ERRORE" per fase; i dettagli sono nel registro cifrato dentro l'app |

- Il workflow parte solo all'orario fissato o a mano: mai da pull request.
- Permessi minimi, azioni fissate al commit, librerie Python con versione e hash verificati.
- La pagina non carica nulla da altri siti (CSP restrittiva, d3 incluso).
- Le frasi segrete non viaggiano mai: la chiave viene ricavata sul dispositivo e salvata come chiave non esportabile.

L'accesso a Garmin Connect non è ufficiale (libreria `garminconnect`): Garmin può cambiarlo o limitarlo.

## Segreti richiesti (Settings → Secrets and variables → Actions)

- `STATE_KEY`: generata da `python -m cloud.seed`, non va mai copiata altrove.
- `DATA_PASSPHRASE`: frase segreta per aprire la dashboard, almeno 20 caratteri (meglio 5 o più parole).
- `GARMIN_EMAIL`, `GARMIN_PASSWORD`: solo per il primo accesso.

Proteggi l'account GitHub con la verifica in due passaggi.
