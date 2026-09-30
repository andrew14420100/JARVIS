# JARVIS

JARVIS è un assistente locale per Windows progettato per usare modelli caricati in LM Studio come cervello. Il progetto separa il **corpo** di Jarvis (interfaccia, voce, strumenti e stati) dal modello AI, così da poter cambiare o instradare più modelli senza riscrivere la UI.

## Stato attuale

### Core e agent
- Connessione a LM Studio tramite API OpenAI-compatible (`/v1`).
- Rilevamento automatico del primo modello caricato tramite `/v1/models`.
- Agent loop con tool calling reale.
- Stati interni: `IDLE`, `THINKING`, `EXECUTING`, `SPEAKING`, `ERROR`.
- Memoria locale SQLite con recupero contestuale.
- La memoria automatica evita intenzionalmente password, PIN, carte, API key e altri dati sensibili evidenti.
- Flusso reale di conferma: strumenti delicati vengono eseguiti solo dopo una risposta esplicita come `confermo`.
- API FastAPI e CLI testuale.
- Nessuna API AI a pagamento obbligatoria.

### Tool desktop già integrati
- CPU, RAM, disco e informazioni sistema;
- apertura applicazioni Windows;
- elenco e focus finestre;
- OCR del testo visibile sullo schermo con coordinate;
- ricerca di testo/pulsanti sullo schermo;
- scroll;
- lettura/impostazione volume;
- timer e notifiche;
- mouse, click, tastiera, screenshot e clipboard dietro conferma esplicita;
- lock, sleep, restart e shutdown dietro conferma esplicita.

### JARVIS Particle UI
Il frontend React usa un renderer **WebGL2** con circa 28.000 particelle:

- core organico;
- sciame esterno;
- filamenti aperti;
- deformazione continua e respirazione;
- HUD fullscreen e boot sequence;
- stati `IDLE`, `LISTENING`, `THINKING`, `EXECUTING`, `SPEAKING`, `ERROR`;
- analisi FFT del microfono nel browser;
- reazione distinta a bassi, medi e alti;
- rendering indipendente dalla velocità del modello AI.

### Voice Core locale
È stata aggiunta una prima integrazione ispirata alle migliori idee di `PanPenek/JarvisAi`, ma adattata all'architettura di questo progetto:

- **Wake word** locale con `openWakeWord` (`hey_jarvis`);
- **Speech-to-text** locale con `faster-whisper`;
- lingua STT predefinita: italiano;
- fallback automatico Whisper da CUDA a CPU;
- registrazione fino al silenzio;
- **Kokoro TTS** locale;
- voce italiana maschile predefinita: `im_nicola`, `lang_code=i`;
- runtime desktop unico in `jarvis/desktop.py`;
- dipendenze voce/desktop separate in `requirements-local.txt`, quindi Emergent non deve installarle.

> Emergent serve per sviluppare e vedere la UI. Wake word, microfono di sistema, controllo desktop, LM Studio e TTS devono girare sul PC Windows locale.

## Installazione preview / Emergent

Per la preview web basta:

```bash
pip install -r requirements.txt
```

Il frontend rimane in `/frontend`, il backend Emergent in `/backend`, mentre il core Python principale è nel package `/jarvis`.

## Installazione completa su Windows

La via più semplice è:

```powershell
.\run-local.ps1
```

Lo script:
1. crea `.venv` se necessario;
2. installa `requirements-local.txt`;
3. scarica i modelli openWakeWord;
4. crea `.env` da `.env.example` se manca;
5. avvia il runtime desktop locale.

Prima di lanciarlo:
1. apri LM Studio;
2. carica un modello;
3. avvia il server locale sulla porta `1234`.

Avvio manuale equivalente:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-local.txt
python -c "from openwakeword import utils; utils.download_models()"
python -m jarvis.desktop
```

Il runtime apre automaticamente:

```text
http://127.0.0.1:8000
```

e resta in ascolto della wake word configurata.

## Avvio solo web/API

```powershell
.\run.ps1
```

oppure:

```powershell
uvicorn jarvis.app:app --host 127.0.0.1 --port 8000 --reload
```

## Configurazione principale

```env
JARVIS_LM_STUDIO_BASE_URL=http://127.0.0.1:1234/v1
JARVIS_MODEL=
JARVIS_MAX_AGENT_ITERATIONS=8
JARVIS_REQUEST_TIMEOUT_SECONDS=120
JARVIS_USER_NAME=Signore

JARVIS_MEMORY_ENABLED=true
JARVIS_MEMORY_DB_PATH=data/jarvis_memory.sqlite3
JARVIS_MEMORY_TOP_K=4

JARVIS_VOICE_ENABLED=true
JARVIS_WAKE_MODEL=hey_jarvis
JARVIS_WAKE_THRESHOLD=0.50

JARVIS_STT_MODEL=small
JARVIS_STT_DEVICE=auto
JARVIS_STT_COMPUTE_TYPE=int8
JARVIS_STT_LANGUAGE=it

JARVIS_TTS_ENABLED=true
JARVIS_TTS_VOICE=im_nicola
JARVIS_TTS_SPEED=1.05
JARVIS_TTS_LANG_CODE=i
```

Lasciando `JARVIS_MODEL` vuoto, JARVIS usa automaticamente il primo modello restituito da LM Studio.

## API utili

```text
GET    /api/health
GET    /api/capabilities
GET    /api/models
POST   /api/chat
POST   /api/reset
GET    /api/memory
DELETE /api/memory/{id}
```

`/api/capabilities` mostra se Whisper, Kokoro e openWakeWord sono realmente installati sul computer.

## Architettura

```text
                   TU
                   |
          +--------+---------+
          |                  |
      testo/UI          "Hey Jarvis"
                             |
                       openWakeWord
                             |
                      faster-whisper
          |                  |
          +---------+--------+
                    v
              JARVIS CORE
                    |
              Local Memory
                    |
             Agent + Tools
                    |
                LM Studio
                    |
                  TTS
                    |
                 Kokoro
                    |
              Particle UI
```

## Memoria locale

La memoria è salvata in SQLite sul computer. Jarvis richiama solo fatti pertinenti alla richiesta corrente. La memorizzazione automatica avviene per frasi esplicite come `Ricorda che...`, `Preferisco...` o indicazioni sul progetto, e blocca diversi pattern sensibili evidenti.

Puoi vedere i ricordi con:

```text
GET /api/memory
```

e cancellarne uno con:

```text
DELETE /api/memory/ID
```

## Prossimi passaggi

### Multi-model router
- modello rapido;
- modello intermedio;
- modello potente;
- classificazione automatica della richiesta;
- escalation automatica se il primo modello fallisce;
- caricamento/scaricamento intelligente per non saturare VRAM e RAM.

### Desktop / Agent
- browser agent più evoluto;
- web search locale/gratuita;
- Git / GitHub / VS Code;
- media control;
- skill e routine;
- barge-in: interrompere Jarvis mentre parla;
- sincronizzazione dell'audio TTS con il core WebGL.

## Sicurezza

LM Studio deve restare privato su `localhost`. Se JARVIS verrà esposto fuori dal PC, verrà pubblicato soltanto un gateway autenticato e mai direttamente la porta `1234`.

Le azioni distruttive devono passare dalle policy nel codice (`SAFE`, `CONFIRMATION_REQUIRED`, `BLOCKED`) e non essere affidate esclusivamente al modello.
