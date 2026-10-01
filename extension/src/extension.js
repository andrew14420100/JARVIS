'use strict';

const vscode = require('vscode');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { scanBrain, radarEntries } = require('./brain');

const panels = new Set();

function workspaceRoot() {
  const folder = vscode.workspace.workspaceFolders?.[0];
  return folder?.uri.fsPath || null;
}

function memoryRoot() {
  const root = workspaceRoot();
  if (!root) return null;
  const configured = vscode.workspace.getConfiguration('jarvis').get('memoryRoot', 'brain');
  return path.isAbsolute(configured) ? configured : path.join(root, configured);
}

function ensureFile(file, content) {
  if (fs.existsSync(file)) return false;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, content, 'utf8');
  return true;
}

function ensureBrainFiles() {
  const root = memoryRoot();
  if (!root) throw new Error('Apri prima la cartella del progetto JARVIS in VS Code.');
  fs.mkdirSync(root, { recursive: true });
  const seeds = [
    ['INDEX.md', `---\ntype: core\ntags: [jarvis, brain]\n---\n# JARVIS\n\nCentro della memoria persistente.\n\n- [[context/CONTEXT]]\n- [[systems/MEMORY]]\n- [[systems/VOICE]]\n- [[systems/TOOLS]]\n- [[radar/RADAR]]\n- [[radar/ADS]]\n`],
    ['context/CONTEXT.md', `---\ntype: context\ntags: [context, brain]\n---\n# CONTEXT\n\nContesto operativo corrente di JARVIS.\n\nCollegato a [[JARVIS]] e [[systems/MEMORY]].\n`],
    ['systems/MEMORY.md', `---\ntype: system\ntags: [memory, foam]\n---\n# MEMORY\n\nMemoria Markdown compatibile con Foam. I wikilink costruiscono la rete del cervello.\n\nCollegato a [[JARVIS]], [[context/CONTEXT]] e [[systems/TOOLS]].\n`],
    ['systems/VOICE.md', `---\ntype: system\ntags: [voice, tts]\n---\n# VOICE\n\nVoce clonata JARVIS conservata nella cartella voice del progetto.\n\nCollegato a [[JARVIS]] e [[systems/TOOLS]].\n`],
    ['systems/TOOLS.md', `---\ntype: system\ntags: [tools, claude-code]\n---\n# TOOLS\n\nStrumenti e automazioni disponibili al cervello.\n\nCollegato a [[JARVIS]], [[systems/MEMORY]] e [[radar/RADAR]].\n`],
    ['radar/RADAR.md', `---\ntype: radar\ntags: [radar]\n---\n# RADAR\n\nSegnali, eventi e cose da sorvegliare.\n\nCollegato a [[JARVIS]] e [[radar/ADS]].\n`],
    ['radar/ADS.md', `---\ntype: radar\ntags: [radar, ads]\n---\n# ADS\n\nCanale radar dedicato ai segnali ADS.\n\nCollegato a [[radar/RADAR]].\n`]
  ];
  let created = 0;
  for (const [relative, content] of seeds) created += ensureFile(path.join(root, relative), content) ? 1 : 0;
  return { root, created };
}

function nonce() {
  return crypto.randomBytes(16).toString('hex');
}

function jsonForHtml(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026');
}

function mediaUri(webview, context, name) {
  return webview.asWebviewUri(vscode.Uri.joinPath(context.extensionUri, 'media', name));
}

function getBrainHtml(webview, context, graph) {
  const script = mediaUri(webview, context, 'brain-grid.bundle.js');
  const n = nonce();
  const payload = jsonForHtml(graph);
  return `<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src ${webview.cspSource} data:; style-src 'unsafe-inline'; script-src ${webview.cspSource} 'nonce-${n}';">
<title>JARVIS · Griglia del Cervello</title>
<style>
html,body,#graph{width:100%;height:100%;margin:0;overflow:hidden;background:#02040a;color:#c9f6ff;font-family:Inter,Segoe UI,Arial,sans-serif}*{box-sizing:border-box}
#graph{position:fixed;inset:0}.hud{position:fixed;z-index:5;pointer-events:none}.brand{top:24px;left:28px;letter-spacing:.26em;font-size:12px;color:#63e7ff;text-shadow:0 0 18px #0cc}.brand b{display:block;font-size:22px;letter-spacing:.42em;color:#e8fdff;margin-bottom:6px}.stats{top:26px;right:28px;text-align:right;font-size:11px;letter-spacing:.14em;color:#8fd7e7}.stats strong{font-size:26px;color:#fff;font-weight:300}.legend{right:28px;bottom:28px;border:1px solid rgba(82,218,255,.22);background:rgba(2,7,15,.62);backdrop-filter:blur(10px);padding:12px 14px;min-width:180px;font-size:10px;letter-spacing:.12em}.legend-row{display:flex;align-items:center;gap:8px;margin:7px 0}.dot{width:7px;height:7px;border-radius:50%;box-shadow:0 0 10px currentColor}.footer{left:28px;bottom:26px;font-size:10px;letter-spacing:.16em;color:#5a94a2}.scan{position:fixed;z-index:3;left:0;right:0;height:1px;background:linear-gradient(90deg,transparent,rgba(78,233,255,.55),transparent);box-shadow:0 0 14px rgba(78,233,255,.35);animation:scan 7s linear infinite;pointer-events:none}@keyframes scan{0%{top:5%}50%{top:95%}100%{top:5%}}
.corner{position:fixed;width:54px;height:54px;border-color:rgba(76,218,255,.38);z-index:4;pointer-events:none}.c1{left:14px;top:14px;border-left:1px solid;border-top:1px solid}.c2{right:14px;top:14px;border-right:1px solid;border-top:1px solid}.c3{left:14px;bottom:14px;border-left:1px solid;border-bottom:1px solid}.c4{right:14px;bottom:14px;border-right:1px solid;border-bottom:1px solid}
</style></head><body>
<div id="graph"></div><div class="scan"></div><div class="corner c1"></div><div class="corner c2"></div><div class="corner c3"></div><div class="corner c4"></div>
<div class="hud brand"><b>JARVIS</b>BRAIN GRID // ONLINE</div>
<div class="hud stats"><strong id="neuronCount">${graph.stats.neurons}</strong><br>NEURONI ONLINE<br><span id="synapseCount">${graph.stats.synapses}</span> SINAPSI</div>
<div class="hud legend" id="legend"></div><div class="hud footer">DOPPIO CLICK SU UN NODO · APRI MEMORIA &nbsp; // &nbsp; FOAM COMPATIBLE</div>
<script nonce="${n}">window.__JARVIS_GRAPH__=${payload};</script><script src="${script}"></script></body></html>`;
}

function getRadarHtml(webview, context, entries, mode) {
  const script = mediaUri(webview, context, 'radar.bundle.js');
  const n = nonce();
  const payload = jsonForHtml({ entries, mode });
  return `<!doctype html><html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src ${webview.cspSource} 'nonce-${n}';"><title>JARVIS Radar</title>
<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#02060a;color:#bcf5ff;font-family:Inter,Segoe UI,Arial,sans-serif}canvas{position:fixed;inset:0}.title{position:fixed;left:28px;top:26px;z-index:2;letter-spacing:.32em;color:#70ecff;font-size:12px}.title b{display:block;color:white;font-size:23px;letter-spacing:.45em;margin-bottom:6px}.signals{position:fixed;z-index:3;right:24px;top:24px;bottom:24px;width:min(360px,32vw);padding:18px;border:1px solid rgba(77,220,255,.22);background:rgba(2,9,15,.64);backdrop-filter:blur(12px);overflow:auto}.signals h3{font-weight:400;letter-spacing:.18em;font-size:11px;color:#78dff3}.signal{border-top:1px solid rgba(100,220,255,.12);padding:12px 0}.signal b{font-size:12px;letter-spacing:.08em}.signal small{display:block;margin-top:5px;color:#5b98a5}.empty{color:#54717a;font-size:12px;margin-top:20px}.corner{position:fixed;inset:14px;pointer-events:none;border:1px solid rgba(79,220,255,.1);z-index:1}</style></head><body>
<canvas id="radar"></canvas><div class="corner"></div><div class="title"><b>JARVIS</b>${mode === 'ads' ? 'RADAR ADS' : 'RADAR'} // ONLINE</div><div class="signals"><h3>SEGNALI RILEVATI · <span id="signalCount">${entries.length}</span></h3><div id="signalList"></div></div>
<script nonce="${n}">window.__JARVIS_RADAR__=${payload};</script><script src="${script}"></script></body></html>`;
}

function trackPanel(panel, update, root) {
  panels.add(panel);
  let timer = null;
  const watcher = fs.existsSync(root) ? vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(root, '**/*.md')) : null;
  const trigger = () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      try { update(); } catch (err) { console.error('[JARVIS] refresh failed', err); }
    }, 180);
  };
  if (watcher) {
    watcher.onDidCreate(trigger);
    watcher.onDidChange(trigger);
    watcher.onDidDelete(trigger);
  }
  panel.onDidDispose(() => {
    clearTimeout(timer);
    watcher?.dispose();
    panels.delete(panel);
  });
}

async function openMemoryNode(root, relative) {
  if (!relative || relative.includes('..')) return;
  const full = path.join(root, relative);
  if (!fs.existsSync(full)) return;
  const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(full));
  await vscode.window.showTextDocument(doc, { preview: false, viewColumn: vscode.ViewColumn.One });
}

function openBrainGrid(context) {
  const root = memoryRoot();
  if (!root) return vscode.window.showErrorMessage('JARVIS: apri prima la cartella del progetto.');
  ensureBrainFiles();
  const panel = vscode.window.createWebviewPanel('jarvisBrainGrid', 'JARVIS · Griglia del Cervello', vscode.ViewColumn.Beside, {
    enableScripts: true,
    retainContextWhenHidden: true,
    localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')]
  });
  const graph = scanBrain(root);
  panel.webview.html = getBrainHtml(panel.webview, context, graph);
  panel.webview.onDidReceiveMessage(async message => {
    if (message?.type === 'openNode') await openMemoryNode(root, message.relative);
  });
  trackPanel(panel, () => panel.webview.postMessage({ type: 'graph', graph: scanBrain(root) }), root);
  return panel;
}

function openRadar(context, mode = 'all') {
  const root = memoryRoot();
  if (!root) return vscode.window.showErrorMessage('JARVIS: apri prima la cartella del progetto.');
  ensureBrainFiles();
  const filter = mode === 'ads' ? 'ads' : '';
  const entries = radarEntries(root, filter);
  const panel = vscode.window.createWebviewPanel('jarvisRadar', mode === 'ads' ? 'JARVIS · Radar Ads' : 'JARVIS · Radar', vscode.ViewColumn.Beside, {
    enableScripts: true,
    retainContextWhenHidden: true,
    localResourceRoots: [vscode.Uri.joinPath(context.extensionUri, 'media')]
  });
  panel.webview.html = getRadarHtml(panel.webview, context, entries, mode);
  panel.webview.onDidReceiveMessage(async message => {
    if (message?.type === 'openNode') await openMemoryNode(root, message.relative);
  });
  trackPanel(panel, () => panel.webview.postMessage({ type: 'radar', entries: radarEntries(root, filter), mode }), root);
  return panel;
}

async function installBrain() {
  try {
    const result = ensureBrainFiles();
    try {
      await vscode.commands.executeCommand('workbench.extensions.installExtension', 'foam.foam-vscode');
    } catch (err) {
      console.warn('[JARVIS] Foam install command unavailable:', err?.message || err);
    }
    const index = path.join(result.root, 'INDEX.md');
    const doc = await vscode.workspace.openTextDocument(index);
    await vscode.window.showTextDocument(doc, { preview: false, viewColumn: vscode.ViewColumn.One });
    vscode.window.showInformationMessage(`JARVIS: cervello online. ${result.created} nuovi nodi creati.`);
  } catch (err) {
    vscode.window.showErrorMessage(`JARVIS: ${err.message}`);
  }
}

function activate(context) {
  const status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 1000);
  status.text = '$(radio-tower) JARVIS · BRAIN ONLINE';
  status.tooltip = 'Apri la Griglia del Cervello';
  status.command = 'jarvis.brainGrid';
  status.show();
  context.subscriptions.push(status);

  context.subscriptions.push(vscode.commands.registerCommand('jarvis.open', () => openBrainGrid(context)));
  context.subscriptions.push(vscode.commands.registerCommand('jarvis.brainGrid', () => openBrainGrid(context)));
  context.subscriptions.push(vscode.commands.registerCommand('jarvis.radar', () => openRadar(context, 'all')));
  context.subscriptions.push(vscode.commands.registerCommand('jarvis.radarAds', () => openRadar(context, 'ads')));
  context.subscriptions.push(vscode.commands.registerCommand('jarvis.installBrain', () => installBrain()));
  context.subscriptions.push(vscode.window.registerUriHandler({
    handleUri: async uri => {
      const command = String(uri.path || '').replace(/^\//, '').toLowerCase();
      if (command === 'radar') return openRadar(context, 'all');
      if (command === 'radar-ads' || command === 'radarads') return openRadar(context, 'ads');
      if (command === 'install') return installBrain();
      return openBrainGrid(context);
    }
  }));

  if (workspaceRoot()) {
    try { ensureBrainFiles(); } catch (err) { console.warn('[JARVIS]', err?.message || err); }
    if (vscode.workspace.getConfiguration('jarvis').get('autoOpen', false)) {
      setTimeout(() => openBrainGrid(context), 650);
    }
  }
}

function deactivate() {
  for (const panel of panels) {
    try { panel.dispose(); } catch (_) {}
  }
}

module.exports = { activate, deactivate };
