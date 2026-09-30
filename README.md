# JARVIS

JARVIS è un assistente locale per Windows progettato per usare modelli caricati in LM Studio come cervello. Il progetto separa il **corpo** di Jarvis (interfaccia, voce, strumenti e stati) dal modello AI, così da poter cambiare o instradare più modelli senza riscrivere la UI.

## Stato attuale

### Core e agent
- Connessione a LM Studio tramite API OpenAI-compatible (`/v1`).
- Rilevamento automatico del primo modello caricato tramite `/v1/models`.
- Agent loop con tool calling reale.
- Stati interni: `IDLE`, `THINKING`, `EXECUTING`, `SPEAKING`, `ERROR`.
- Tool reali:
  - `get_cpu_usage`
  - `get_ram_usage`
  - `get_system_information`
  - `open_application` (Windows)
- API FastAPI e CLI testuale.
- Nessuna API AI a pagamento obbligatoria.

### JARVIS Particle UI
La precedente sfera CSS è stata sostituita da un renderer particellare realtime costruito direttamente nel frontend:

- core organico formato da migliaia di particelle;
- campo di particelle esterne in orbita;
- deformazione continua e respirazione del core;
- HUD fullscreen;
- boot sequence;
- animazioni differenti per `IDLE`, `LISTENING`, `THINKING`, `EXECUTING`, `SPEAKING` ed `ERROR`;
- reazione in tempo reale all'audio del microfono tramite Web Audio API + FFT;
- basse/medie frequenze usate per aumentare energia e deformazione del core;
- interfaccia indipendente dalla velocità del modello: il renderer continua a funzionare mentre LM Studio elabora una richiesta;
- indicatore FPS, livello audio, stato connessione e modello attivo.

> La modalità microfono attuale pilota il visualizzatore audio. Trascrizione locale, wake word e TTS verranno collegati nei passaggi successivi.

## Requisiti

- Windows 11 consigliato.
- Python 3.11+.
- LM Studio.
- Un modello compatibile con chat/tool calling caricato in LM Studio.
- Browser moderno con supporto Canvas e Web Audio API.

## Avvio su Windows

1. Apri LM Studio.
2. Carica un modello.
3. Avvia il server locale LM Studio sulla porta `1234`.
4. In PowerShell, dalla cartella del progetto:

```powershell
.\run.ps1
```

5. Apri:

```text
http://127.0.0.1:8000
```

Al primo utilizzo del pulsante microfono il browser chiederà il permesso di usare il microfono.

Per la CLI:

```powershell
.\run-cli.ps1
```

## Test rapido

Puoi provare:

- `Jarvis, quanta RAM sto usando?`
- `Jarvis, qual è l'utilizzo della CPU?`
- `Jarvis, apri Blocco Note.`

CPU e RAM vengono lette realmente dal computer e `open_application` esegue l'azione su Windows.

Per provare il renderer vocale, premi il pulsante del microfono e parla: il core e il campo particellare reagiscono direttamente all'energia della tua voce, senza aspettare il modello AI.

## Configurazione

Copia `.env.example` in `.env` se vuoi cambiare endpoint/modello:

```env
JARVIS_LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
JARVIS_MODEL=
JARVIS_MAX_AGENT_ITERATIONS=8
JARVIS_REQUEST_TIMEOUT_SECONDS=120
JARVIS_USER_NAME=Signore
```

Lasciando `JARVIS_MODEL` vuoto, JARVIS usa automaticamente il primo modello restituito da LM Studio.

## Architettura prevista

```text
Microfono / testo
       |
       v
 JARVIS CORE
       |
       +---- comandi locali immediati
       |
       +---- AI Router
                |
                +---- modello rapido
                +---- modello intermedio
                +---- modello potente
       |
       +---- Tools Windows / Browser / Git / VS Code
       |
       v
 Particle UI + TTS
```

L'obiettivo è evitare di usare un modello grande per ogni comando. Jarvis dovrà scegliere automaticamente il motore più adatto e fare escalation soltanto quando necessario.

## Prossimi passaggi

### Voice Core
- wake word `Jarvis`;
- VAD locale;
- faster-whisper locale;
- TTS locale;
- animazione `SPEAKING` sincronizzata con l'audio prodotto da Jarvis;
- barge-in: possibilità di interrompere Jarvis mentre parla.

### Multi-model router
- supporto a più modelli LM Studio;
- modello rapido, intermedio e potente;
- scelta automatica in base a complessità, strumenti richiesti, coding, vision e numero di passaggi;
- escalation automatica se il primo modello non riesce a completare la richiesta.

### Desktop / Agent
- memoria SQLite;
- visione dello schermo;
- browser agent;
- Git / GitHub / VS Code;
- skill e routine;
- applicazione desktop Windows;
- avvio automatico.

## Sicurezza

LM Studio deve restare privato su `localhost`. Se JARVIS verrà esposto fuori dal PC, verrà pubblicato soltanto un gateway autenticato e mai direttamente la porta `1234`.

Le azioni distruttive future devono passare da policy nel codice (`SAFE`, `CONFIRMATION_REQUIRED`, `BLOCKED`) e non essere affidate esclusivamente al modello.
