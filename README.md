# JARVIS

JARVIS locale ispirato al workflow del video di riferimento: **VS Code + Brain Grid + Foam/Markdown memory + Radar + voce clonata**.

## Comandi VS Code

Apri la Command Palette (`Ctrl+Shift+P`) e trovi:

- `Jarvis: Apri`
- `Jarvis: Griglia del Cervello`
- `Jarvis: Radar`
- `Jarvis: Radar Ads`
- `Jarvis: Installa il cervello`
- `Foam: Show Graph` dopo l'installazione di Foam

La cartella `brain/` e' la memoria persistente. I collegamenti `[[wikilink]]` diventano sinapsi nella Griglia del Cervello e sono leggibili anche da Foam.

## Avvio Windows

```powershell
git pull
powershell -ExecutionPolicy Bypass -File .\run-local.ps1
```

Il launcher compila e installa l'estensione VS Code, installa Foam, apre automaticamente il Brain Grid e poi avvia il runtime vocale con la voce clonata gia' presente in `voice/`.

Per provare soltanto UI/memoria senza avviare il runtime vocale:

```powershell
powershell -ExecutionPolicy Bypass -File .\run-local.ps1 -SkipVoice
```

## Architettura

- `extension/` — estensione VS Code JARVIS e visualizzatori 3D/radar.
- `brain/` — memoria Markdown/Foam versionabile; i dati personali possono essere spostati in `private/`.
- `voice/` — voce clonata esistente, mantenuta invariata.
- `personal-jarvis/` — per ora resta come backplane vocale compatibile mentre il nuovo cervello VS Code prende il posto della vecchia UI.

Il Brain Grid legge i file Markdown in tempo reale: aggiungendo note e wikilink, il numero di neuroni e sinapsi cresce automaticamente.
