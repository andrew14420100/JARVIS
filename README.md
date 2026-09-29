# JARVIS

JARVIS è un assistente desktop locale per Windows progettato per usare un modello Qwen caricato in LM Studio come cervello. Questa repository contiene la **V0.1**: backend locale, vero agent loop, tool calling reale, strumenti di sistema e una prima interfaccia web futuristica.

## Cosa funziona nella V0.1

- Connessione a LM Studio tramite API OpenAI-compatible (`/v1`).
- Rilevamento automatico del primo modello caricato tramite `/v1/models`.
- Agent loop: Qwen può richiedere tool, ricevere i risultati e continuare a ragionare prima della risposta finale.
- Tool reali:
  - `get_cpu_usage`
  - `get_ram_usage`
  - `get_system_information`
  - `open_application` (Windows)
- API FastAPI.
- CLI testuale.
- Prima UI JARVIS con stati visivi.
- Nessuna API AI a pagamento richiesta.

## Requisiti

- Windows 11 consigliato.
- Python 3.11+.
- LM Studio.
- Un modello Qwen compatibile con tool/function calling caricato in LM Studio.

## Avvio

1. Apri LM Studio.
2. Carica Qwen.
3. Avvia il server locale sulla porta 1234.
4. In PowerShell, dalla cartella del progetto:

```powershell
.\run.ps1
```

5. Apri `http://127.0.0.1:8000`.

Per la CLI:

```powershell
.\run-cli.ps1
```

## Test rapido

Prova:

- `Jarvis, quanta RAM sto usando?`
- `Jarvis, qual è l'utilizzo della CPU?`
- `Jarvis, apri Blocco Note.`

JARVIS non deve inventare i valori: CPU e RAM provengono realmente dal computer e `open_application` esegue l'azione su Windows.

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

## Roadmap

### V0.2
- Wake word "Jarvis"
- VAD
- faster-whisper
- TTS locale
- interruzione della voce (barge-in)

### V0.3
- memoria SQLite
- conversazioni recenti
- Oggi / Follow-up / Dettatura

### V0.4
- sfera WebGL/Three.js avanzata
- streaming degli stati dell'agente
- Skill / Routine / Connessioni

### V0.5
- visione dello schermo con modello locale multimodale
- contesto finestra attiva

### V0.6
- Git / GitHub / VS Code / FlixIT
- coding agent con policy di sicurezza

### V1.0
- accesso remoto autenticato
- installazione Windows
- avvio automatico
- pubblicazione sicura senza esporre LM Studio direttamente

## Sicurezza

LM Studio deve restare privato su `localhost`. Quando JARVIS verrà pubblicato, sarà esposto solo il gateway JARVIS autenticato, mai la porta 1234 direttamente su Internet.

Le azioni distruttive future saranno protette da policy nel codice (`SAFE`, `CONFIRMATION_REQUIRED`, `BLOCKED`) e non affidate esclusivamente al modello.
