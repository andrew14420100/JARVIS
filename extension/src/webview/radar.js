const vscode = acquireVsCodeApi();
const canvas = document.getElementById('radar');
const ctx = canvas.getContext('2d');
let payload = window.__JARVIS_RADAR__ || { entries: [], mode: 'all' };
let t = 0;

function resize() {
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(window.innerWidth * dpr);
  canvas.height = Math.round(window.innerHeight * dpr);
  canvas.style.width = `${window.innerWidth}px`;
  canvas.style.height = `${window.innerHeight}px`;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
}
window.addEventListener('resize', resize);
resize();

function hash(value) {
  let h = 2166136261;
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function draw() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const panelWidth = Math.min(360, w * 0.32);
  const cx = Math.max(170, (w - panelWidth) * 0.48);
  const cy = h * 0.54;
  const r = Math.min(w - panelWidth, h) * 0.34;
  ctx.clearRect(0, 0, w, h);

  const bg = ctx.createRadialGradient(cx, cy, 0, cx, cy, r * 1.5);
  bg.addColorStop(0, 'rgba(20,98,114,.13)');
  bg.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, w, h);

  ctx.strokeStyle = 'rgba(71,222,246,.17)';
  ctx.lineWidth = 1;
  for (let ring = 1; ring <= 5; ring++) {
    ctx.beginPath();
    ctx.arc(cx, cy, (r * ring) / 5, 0, Math.PI * 2);
    ctx.stroke();
  }
  for (let i = 0; i < 12; i++) {
    const a = (i / 12) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
    ctx.stroke();
  }

  const sweep = t * 0.008;
  ctx.save();
  ctx.translate(cx, cy);
  ctx.rotate(sweep);
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.arc(0, 0, r, -0.34, 0);
  ctx.closePath();
  ctx.fillStyle = 'rgba(67,229,255,.08)';
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(0, 0);
  ctx.lineTo(r, 0);
  ctx.strokeStyle = '#55edff';
  ctx.shadowColor = '#55edff';
  ctx.shadowBlur = 15;
  ctx.lineWidth = 1.4;
  ctx.stroke();
  ctx.restore();
  ctx.shadowBlur = 0;

  payload.entries.forEach((entry, index) => {
    const hv = hash(entry.id || entry.name || String(index));
    const a = ((hv % 10000) / 10000) * Math.PI * 2;
    const rr = r * (0.16 + (((hv >>> 8) % 7800) / 10000));
    const x = cx + Math.cos(a) * rr;
    const y = cy + Math.sin(a) * rr;
    const pulse = 0.5 + 0.5 * Math.sin(t * 0.025 + index * 1.9);
    const size = 3 + (entry.strength || 0.5) * 5 + pulse * 1.5;
    ctx.beginPath();
    ctx.arc(x, y, size, 0, Math.PI * 2);
    ctx.fillStyle = payload.mode === 'ads' ? `rgba(255,180,74,${0.58 + pulse * 0.3})` : `rgba(88,236,255,${0.58 + pulse * 0.3})`;
    ctx.shadowColor = payload.mode === 'ads' ? '#ffb44a' : '#58ecff';
    ctx.shadowBlur = 14;
    ctx.fill();
    ctx.shadowBlur = 0;
  });

  t += 1;
  requestAnimationFrame(draw);
}

function renderList() {
  const list = document.getElementById('signalList');
  list.replaceChildren();
  document.getElementById('signalCount').textContent = payload.entries.length;
  if (!payload.entries.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = 'Nessun segnale registrato nel cervello.';
    list.appendChild(empty);
    return;
  }
  for (const entry of payload.entries) {
    const row = document.createElement('div');
    row.className = 'signal';
    row.style.cursor = 'pointer';
    const title = document.createElement('b');
    title.textContent = entry.name.toUpperCase();
    const meta = document.createElement('small');
    meta.textContent = `${entry.type} · ${(entry.tags || []).join(' · ') || 'no tags'}`;
    row.append(title, meta);
    row.addEventListener('click', () => vscode.postMessage({ type: 'openNode', relative: entry.relative }));
    list.appendChild(row);
  }
}

renderList();
draw();
window.addEventListener('message', event => {
  if (event.data?.type !== 'radar') return;
  payload = { entries: event.data.entries || [], mode: event.data.mode || 'all' };
  renderList();
});
