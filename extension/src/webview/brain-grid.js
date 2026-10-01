import ForceGraph3D from '3d-force-graph';
import * as THREE from 'three';
import SpriteText from 'three-spritetext';

const vscode = acquireVsCodeApi();
const mount = document.getElementById('graph');

const COLORS = {
  core: '#8df7ff',
  context: '#56d5ff',
  system: '#786cff',
  systems: '#786cff',
  project: '#fa65ff',
  projects: '#fa65ff',
  radar: '#ffb454',
  memory: '#46ffc7',
  daily: '#4fd7a4'
};
const FALLBACK = '#69baff';

function colorFor(type) {
  return COLORS[String(type || '').toLowerCase()] || FALLBACK;
}

function hexToRgba(hex, alpha) {
  const raw = hex.replace('#', '');
  const value = parseInt(raw.length === 3 ? raw.split('').map(c => c + c).join('') : raw, 16);
  const r = (value >> 16) & 255;
  const g = (value >> 8) & 255;
  const b = value & 255;
  return `rgba(${r},${g},${b},${alpha})`;
}

function nodeObject(node) {
  const color = colorFor(node.type);
  const group = new THREE.Group();
  const radius = node.type === 'core' ? 6.4 : 2.5 + Math.min(4.5, (node.degree || 0) * 0.55);
  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(radius, 20, 14),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: node.type === 'core' ? 0.96 : 0.82 })
  );
  sphere.userData.baseRadius = radius;
  group.add(sphere);

  const halo = new THREE.Mesh(
    new THREE.SphereGeometry(radius * 1.75, 16, 10),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.06, depthWrite: false })
  );
  group.add(halo);

  const showLabel = node.type === 'core' || node.degree > 0;
  if (showLabel) {
    const label = new SpriteText(node.name.toUpperCase());
    label.color = node.type === 'core' ? '#ffffff' : color;
    label.textHeight = node.type === 'core' ? 5.2 : 3.2;
    label.backgroundColor = 'rgba(0,5,12,0.42)';
    label.padding = 1.2;
    label.position.y = -(radius + 5);
    label.material.depthWrite = false;
    group.add(label);
  }

  return group;
}

const graph = ForceGraph3D()(mount)
  .backgroundColor('#02040a')
  .showNavInfo(false)
  .nodeLabel(node => `${node.name}<br/><span style="opacity:.62">${node.type} · ${node.degree || 0} link</span>`)
  .nodeThreeObject(nodeObject)
  .linkColor(link => {
    const source = typeof link.source === 'object' ? link.source : null;
    return hexToRgba(colorFor(source?.type), 0.23);
  })
  .linkWidth(link => {
    const source = typeof link.source === 'object' ? link.source : null;
    return source?.type === 'core' ? 1.15 : 0.44;
  })
  .linkDirectionalParticles(1)
  .linkDirectionalParticleWidth(1.15)
  .linkDirectionalParticleSpeed(0.0045)
  .linkDirectionalParticleColor(() => '#6cecff')
  .d3AlphaDecay(0.022)
  .d3VelocityDecay(0.34)
  .warmupTicks(80)
  .cooldownTicks(700);

graph.controls().enableDamping = true;
graph.controls().dampingFactor = 0.055;
graph.controls().autoRotate = true;
graph.controls().autoRotateSpeed = 0.22;

graph.cameraPosition({ x: 0, y: 0, z: 300 });

const starGeometry = new THREE.BufferGeometry();
const starCount = 1100;
const starPositions = new Float32Array(starCount * 3);
for (let i = 0; i < starCount; i++) {
  const radius = 320 + Math.random() * 900;
  const theta = Math.random() * Math.PI * 2;
  const phi = Math.acos(2 * Math.random() - 1);
  starPositions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
  starPositions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
  starPositions[i * 3 + 2] = radius * Math.cos(phi);
}
starGeometry.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
const starMaterial = new THREE.PointsMaterial({ color: 0x4bbbd2, size: 0.9, transparent: true, opacity: 0.28, depthWrite: false });
graph.scene().add(new THREE.Points(starGeometry, starMaterial));

let lastNode = null;
let lastClick = 0;
graph.onNodeClick(node => {
  const now = Date.now();
  if (lastNode?.id === node.id && now - lastClick < 380) {
    vscode.postMessage({ type: 'openNode', relative: node.relative });
    lastNode = null;
    lastClick = 0;
    return;
  }
  lastNode = node;
  lastClick = now;
  const distance = 82;
  const distRatio = 1 + distance / Math.hypot(node.x || 1, node.y || 1, node.z || 1);
  graph.cameraPosition(
    { x: (node.x || 1) * distRatio, y: (node.y || 1) * distRatio, z: (node.z || 1) * distRatio },
    node,
    900
  );
});

graph.onNodeHover(node => {
  document.body.style.cursor = node ? 'pointer' : 'default';
  graph.controls().autoRotate = !node;
});

function renderLegend(data) {
  const legend = document.getElementById('legend');
  legend.replaceChildren();
  const header = document.createElement('div');
  header.textContent = 'SETTORI DEL CERVELLO';
  header.style.color = '#d7fbff';
  header.style.marginBottom = '8px';
  legend.appendChild(header);
  const types = [...new Set(data.nodes.map(node => node.type))].sort();
  for (const type of types) {
    const row = document.createElement('div');
    row.className = 'legend-row';
    const dot = document.createElement('span');
    dot.className = 'dot';
    dot.style.color = colorFor(type);
    dot.style.background = colorFor(type);
    const text = document.createElement('span');
    text.textContent = String(type).toUpperCase();
    row.append(dot, text);
    legend.appendChild(row);
  }
}

function setData(data) {
  const payload = data || { nodes: [], links: [], stats: { neurons: 0, synapses: 0 } };
  graph.graphData(payload);
  document.getElementById('neuronCount').textContent = payload.stats?.neurons ?? payload.nodes.length;
  document.getElementById('synapseCount').textContent = payload.stats?.synapses ?? payload.links.length;
  renderLegend(payload);
}

setData(window.__JARVIS_GRAPH__);

window.addEventListener('message', event => {
  const message = event.data;
  if (message?.type === 'graph') setData(message.graph);
});

window.addEventListener('resize', () => {
  graph.width(window.innerWidth).height(window.innerHeight);
});

const clock = new THREE.Clock();
(function animatePulse() {
  const t = clock.getElapsedTime();
  graph.scene().traverse(obj => {
    if (obj.isMesh && obj.userData?.baseRadius) {
      const scale = 1 + Math.sin(t * 1.6 + obj.id * 0.03) * 0.035;
      obj.scale.setScalar(scale);
    }
  });
  requestAnimationFrame(animatePulse);
})();
