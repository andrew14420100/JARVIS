import React, { useEffect, useMemo, useRef, useState } from 'react';

const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');

function JarvisCanvas({ visualStateRef, audioLevelRef, audioBandsRef }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas.getContext('2d', { alpha: false });
    let width = 0;
    let height = 0;
    let dpr = 1;
    let cx = 0;
    let cy = 0;
    let raf = 0;
    let lastFrame = performance.now();
    let energy = 0.14;
    let rotation = 0;
    let rotX = 0;
    let mouseX = 0;
    let mouseY = 0;
    let pulsePhase = 0;

    const CORE_COUNT = 3400;
    const DUST_COUNT = 920;
    const FILAMENT_COUNT = 14;
    const core = [];
    const dust = [];
    const filaments = [];
    const golden = Math.PI * (3 - Math.sqrt(5));

    for (let i = 0; i < CORE_COUNT; i += 1) {
      const y = 1 - (i / (CORE_COUNT - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const theta = golden * i;
      const shell = 0.8 + Math.random() * 0.32;
      core.push({
        x: Math.cos(theta) * r * shell,
        y: y * shell,
        z: Math.sin(theta) * r * shell,
        size: 0.34 + Math.random() * 1.22,
        phase: Math.random() * Math.PI * 2,
        phase2: Math.random() * Math.PI * 2,
        alpha: 0.24 + Math.random() * 0.76,
        detach: Math.random(),
      });
    }

    for (let i = 0; i < DUST_COUNT; i += 1) {
      dust.push({
        angle: Math.random() * Math.PI * 2,
        radius: 0.92 + Math.pow(Math.random(), 0.38) * 2.9,
        z: (Math.random() - 0.5) * 3.2,
        speed: (0.022 + Math.random() * 0.15) * (Math.random() < 0.5 ? -1 : 1),
        size: 0.28 + Math.random() * 1.15,
        alpha: 0.05 + Math.random() * 0.46,
        phase: Math.random() * Math.PI * 2,
        eccentricity: 0.66 + Math.random() * 0.5,
      });
    }

    for (let i = 0; i < FILAMENT_COUNT; i += 1) {
      filaments.push({
        angle: (i / FILAMENT_COUNT) * Math.PI * 2 + Math.random() * 0.5,
        length: 1.25 + Math.random() * 1.1,
        width: 0.45 + Math.random() * 0.7,
        speed: 0.06 + Math.random() * 0.11,
        phase: Math.random() * Math.PI * 2,
        bend: (Math.random() - 0.5) * 0.9,
      });
    }

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 1.7);
      width = window.innerWidth;
      height = window.innerHeight;
      cx = width * 0.5;
      cy = height * 0.465;
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const onPointerMove = (event) => {
      mouseX = (event.clientX / width - 0.5) * 2;
      mouseY = (event.clientY / height - 0.5) * 2;
    };

    const rotatePoint = (x, y, z, rx, ry) => {
      const cosy = Math.cos(ry);
      const siny = Math.sin(ry);
      const cosx = Math.cos(rx);
      const sinx = Math.sin(rx);
      const x1 = x * cosy - z * siny;
      const z1 = x * siny + z * cosy;
      const y1 = y * cosx - z1 * sinx;
      const z2 = y * sinx + z1 * cosx;
      return [x1, y1, z2];
    };

    const stateEnergy = {
      IDLE: 0.14,
      LISTENING: 0.42,
      THINKING: 0.78,
      EXECUTING: 0.98,
      SPEAKING: 0.62,
      ERROR: 0.27,
    };

    const stateSpeed = {
      IDLE: 0.72,
      LISTENING: 1.2,
      THINKING: 2.3,
      EXECUTING: 3.0,
      SPEAKING: 1.55,
      ERROR: 0.5,
    };

    const organicNoise = (angle, time, intensity, bass, mid) => {
      const n1 = Math.sin(angle * 3 + time * 0.72);
      const n2 = Math.sin(angle * 5 - time * 0.53 + 1.7);
      const n3 = Math.cos(angle * 9 + time * 0.34 - 0.8);
      const voice = Math.sin(angle * 7 - time * 6.5) * mid;
      return (n1 * 0.045 + n2 * 0.026 + n3 * 0.014) * intensity + voice * 0.055 + bass * 0.035;
    };

    const drawOrganicMembrane = (base, t, visualState, bass, mid, high) => {
      const stateBoost = visualState === 'THINKING' ? 1.42 : visualState === 'EXECUTING' ? 1.65 : visualState === 'LISTENING' ? 1.18 : 1;
      const points = 170;
      const radius = base * (0.88 + bass * 0.12 + Math.sin(t * 1.25) * 0.012);
      ctx.save();
      ctx.translate(cx, cy);
      ctx.globalCompositeOperation = 'lighter';

      const membrane = ctx.createRadialGradient(0, 0, base * 0.04, 0, 0, base * 1.05);
      membrane.addColorStop(0, `rgba(205,250,255,${0.05 + energy * 0.05})`);
      membrane.addColorStop(0.46, `rgba(41,205,240,${0.035 + energy * 0.04})`);
      membrane.addColorStop(0.83, `rgba(23,175,220,${0.018 + energy * 0.03})`);
      membrane.addColorStop(1, 'rgba(0,95,135,0)');

      ctx.beginPath();
      for (let i = 0; i <= points; i += 1) {
        const angle = (i / points) * Math.PI * 2;
        const localNoise = organicNoise(angle, t, stateBoost + energy * 0.55, bass, mid);
        const highRipple = Math.sin(angle * 17 + t * 10.5) * high * 0.022;
        const rr = radius * (1 + localNoise + highRipple);
        const x = Math.cos(angle) * rr;
        const y = Math.sin(angle) * rr * (0.96 + Math.sin(t * 0.43) * 0.012);
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.fillStyle = membrane;
      ctx.fill();
      ctx.strokeStyle = `rgba(104,231,255,${0.08 + energy * 0.1 + high * 0.09})`;
      ctx.lineWidth = 0.65 + high * 0.7;
      ctx.shadowBlur = 16 + energy * 18;
      ctx.shadowColor = 'rgba(75,224,255,.42)';
      ctx.stroke();
      ctx.shadowBlur = 0;

      for (let layer = 0; layer < 3; layer += 1) {
        ctx.beginPath();
        const layerRadius = radius * (0.54 + layer * 0.13);
        for (let i = 0; i <= 110; i += 1) {
          const angle = (i / 110) * Math.PI * 2;
          const wobble = Math.sin(angle * (4 + layer * 2) + t * (0.8 + layer * 0.22) + layer) * (0.035 + mid * 0.04);
          const rr = layerRadius * (1 + wobble);
          const x = Math.cos(angle) * rr;
          const y = Math.sin(angle) * rr * (0.9 + layer * 0.025);
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
        ctx.strokeStyle = `rgba(84,222,250,${0.028 + energy * 0.025})`;
        ctx.lineWidth = 0.45;
        ctx.stroke();
      }

      ctx.restore();
    };

    const drawFilaments = (base, t, visualState, bass, mid, high) => {
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      const activeBoost = visualState === 'THINKING' || visualState === 'EXECUTING' ? 1.7 : visualState === 'LISTENING' ? 1.25 : 0.8;

      for (const f of filaments) {
        const a = f.angle + t * f.speed * activeBoost;
        const startR = base * (0.62 + Math.sin(t * 0.7 + f.phase) * 0.05);
        const endR = base * (f.length + energy * 0.42 + high * 0.22);
        const sx = cx + Math.cos(a) * startR;
        const sy = cy + Math.sin(a) * startR * 0.72;
        const ex = cx + Math.cos(a + f.bend) * endR;
        const ey = cy + Math.sin(a + f.bend) * endR * 0.68;
        const bendR = base * (0.6 + f.width);
        const c1x = cx + Math.cos(a + 0.55 + f.bend * 0.4) * bendR;
        const c1y = cy + Math.sin(a + 0.55 + f.bend * 0.4) * bendR * 0.84;
        const c2x = cx + Math.cos(a + f.bend * 0.75) * endR * 0.78;
        const c2y = cy + Math.sin(a + f.bend * 0.75) * endR * 0.58;
        const alpha = (0.018 + energy * 0.038 + mid * 0.055) * (0.65 + 0.35 * Math.sin(t * 1.7 + f.phase));

        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.bezierCurveTo(c1x, c1y, c2x, c2y, ex, ey);
        ctx.strokeStyle = `rgba(72,219,252,${Math.max(0, alpha)})`;
        ctx.lineWidth = 0.45 + bass * 0.65;
        ctx.stroke();

        const sparkPhase = (t * (0.15 + f.speed) * activeBoost + f.phase) % 1;
        const u = sparkPhase;
        const inv = 1 - u;
        const px = inv * inv * inv * sx + 3 * inv * inv * u * c1x + 3 * inv * u * u * c2x + u * u * u * ex;
        const py = inv * inv * inv * sy + 3 * inv * inv * u * c1y + 3 * inv * u * u * c2y + u * u * u * ey;
        ctx.fillStyle = `rgba(154,244,255,${0.12 + energy * 0.28 + high * 0.22})`;
        ctx.beginPath();
        ctx.arc(px, py, 0.8 + high * 1.4, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    };

    const drawRings = (base, t, visualState, high) => {
      const ringSpeed = visualState === 'THINKING' ? 2.1 : visualState === 'EXECUTING' ? 2.8 : 1;
      const rings = [
        [1.22, 0.26, 0.07, 5],
        [1.43, 0.54, -0.047, 12],
        [1.66, 0.84, 0.028, 3],
      ];
      rings.forEach(([radius, tilt, speed, dash], index) => {
        ctx.save();
        ctx.translate(cx, cy);
        ctx.rotate(t * speed * ringSpeed + index * 0.3);
        ctx.scale(1, tilt);
        ctx.beginPath();
        ctx.arc(0, 0, base * radius * (1 + high * 0.015), 0, Math.PI * 2);
        ctx.strokeStyle = `rgba(73,209,239,${0.035 + energy * 0.038})`;
        ctx.lineWidth = 0.55;
        ctx.setLineDash([dash, dash * 1.7]);
        ctx.stroke();
        ctx.restore();
      });
    };

    const render = (now) => {
      const dt = Math.min((now - lastFrame) / 1000, 0.05);
      lastFrame = now;
      const audio = audioLevelRef.current || 0;
      const bands = audioBandsRef.current || { bass: 0, mid: 0, high: 0 };
      const bass = bands.bass || 0;
      const mid = bands.mid || 0;
      const high = bands.high || 0;
      const visualState = visualStateRef.current || 'IDLE';
      const targetEnergy = (stateEnergy[visualState] ?? 0.2) + audio * 0.68 + bass * 0.2;
      energy += (Math.min(targetEnergy, 1.42) - energy) * 0.07;
      const speed = stateSpeed[visualState] || 1;
      const t = now * 0.001;
      const base = Math.min(width, height) * (width < 700 ? 0.17 : 0.188);
      pulsePhase += dt * (0.8 + energy * 1.4 + bass * 2.2);

      const background = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(width, height) * 0.78);
      background.addColorStop(0, `rgb(${2 + Math.floor(energy * 3)},${11 + Math.floor(energy * 9)},${17 + Math.floor(energy * 14)})`);
      background.addColorStop(0.36, '#02080c');
      background.addColorStop(1, '#010305');
      ctx.fillStyle = background;
      ctx.fillRect(0, 0, width, height);

      rotation += dt * (0.085 + energy * 0.18) * speed;
      rotX += (mouseY * 0.095 + 0.07 * Math.sin(t * 0.23) - rotX) * 0.018;
      const rotY = rotation + mouseX * 0.11;

      const aura = ctx.createRadialGradient(cx, cy, base * 0.08, cx, cy, base * (1.55 + energy * 0.2));
      aura.addColorStop(0, `rgba(124,239,255,${0.075 + energy * 0.08})`);
      aura.addColorStop(0.34, `rgba(31,190,230,${0.032 + energy * 0.045})`);
      aura.addColorStop(0.7, `rgba(4,100,145,${0.012 + energy * 0.012})`);
      aura.addColorStop(1, 'rgba(0,70,110,0)');
      ctx.fillStyle = aura;
      ctx.beginPath();
      ctx.arc(cx, cy, base * 1.75, 0, Math.PI * 2);
      ctx.fill();

      drawRings(base, t, visualState, high);
      drawFilaments(base, t, visualState, bass, mid, high);
      drawOrganicMembrane(base, t, visualState, bass, mid, high);

      ctx.globalCompositeOperation = 'lighter';

      for (const p of dust) {
        p.angle += p.speed * dt * speed * (1 + energy * 1.3);
        const pulse = Math.sin(t * (0.5 + Math.abs(p.speed) * 2.4) + p.phase);
        const breathingOrbit = 1 + Math.sin(pulsePhase + p.phase) * 0.018 + high * 0.035 * pulse;
        const rr = p.radius * breathingOrbit;
        const x = Math.cos(p.angle) * rr;
        const z = Math.sin(p.angle) * rr * p.eccentricity;
        const y = p.z * 0.48 + Math.sin(p.angle * 1.65 + p.phase) * (0.11 + mid * 0.08);
        const q = rotatePoint(x, y, z, rotX * 0.33, rotY * 0.27);
        const depth = 4 + q[2];
        if (depth <= 0.2) continue;
        const persp = 3.35 / depth;
        const px = cx + q[0] * base * 0.73 * persp;
        const py = cy + q[1] * base * 0.73 * persp;
        const alpha = p.alpha * (0.25 + energy * 0.62 + high * 0.18) * (0.48 + 0.52 * Math.sin(t * 1.65 + p.phase));
        ctx.fillStyle = `rgba(79,218,251,${Math.max(0, Math.min(alpha, 0.78))})`;
        ctx.beginPath();
        ctx.arc(px, py, p.size * (0.55 + persp * 0.48) * (1 + high * 0.25), 0, Math.PI * 2);
        ctx.fill();
      }

      for (const p of core) {
        const n1 = Math.sin(p.x * 5.6 + p.y * 2.8 + t * (0.68 + energy * 0.6) + p.phase);
        const n2 = Math.cos(p.z * 6.4 - p.x * 3.1 - t * 0.51 + p.phase2);
        const n3 = Math.sin((p.x + p.z) * 9.1 + t * 0.34 + p.phase * 0.45);
        const voiceLow = Math.sin((p.y + 1) * 5.5 - t * 4.2 + p.phase * 0.1) * bass;
        const voiceMid = Math.sin((p.x + 1) * 10 - t * 7.2 + p.phase2 * 0.2) * mid;
        const voiceHigh = Math.cos((p.z + 1) * 18 + t * 11.5 + p.phase) * high;
        const stateDistortion = visualState === 'THINKING' ? 1.45 : visualState === 'EXECUTING' ? 1.72 : visualState === 'LISTENING' ? 1.18 : 1;
        let distortion = 1 + n1 * (0.018 + energy * 0.044) * stateDistortion + n2 * (0.01 + energy * 0.025) + n3 * 0.012;
        distortion += voiceLow * 0.075 + voiceMid * 0.046 + voiceHigh * 0.018;

        const detachThreshold = visualState === 'THINKING' ? 0.9 : visualState === 'EXECUTING' ? 0.82 : 0.97;
        const detached = p.detach > detachThreshold;
        const detachWave = detached ? (0.08 + energy * 0.14) * (0.5 + 0.5 * Math.sin(t * 2.4 + p.phase)) : 0;
        const dx = detached ? Math.cos(p.phase) * detachWave : 0;
        const dy = detached ? Math.sin(p.phase2) * detachWave : 0;
        const dz = detached ? Math.cos(p.phase2) * detachWave : 0;

        const q = rotatePoint(p.x * distortion + dx, p.y * distortion + dy, p.z * distortion + dz, rotX, rotY);
        const depth = 3.22 + q[2];
        if (depth <= 0.15) continue;
        const persp = 2.82 / depth;
        const breathe = 1 + Math.sin(pulsePhase) * 0.014 + bass * 0.095;
        const px = cx + q[0] * base * persp * breathe;
        const py = cy + q[1] * base * persp * breathe;
        const front = Math.max(0.06, Math.min((q[2] + 1.28) / 2.55, 1));
        const edge = Math.max(0.15, Math.min(1 - Math.abs(q[2]) * 0.17, 1));
        const flicker = 0.72 + 0.28 * Math.sin(t * (1.8 + energy * 4.4) + p.phase);
        const alpha = Math.max(0.025, Math.min(p.alpha * front * edge * flicker * (0.48 + energy * 0.48 + mid * 0.18), 0.98));
        const size = p.size * (0.58 + persp * 0.8) * (1 + energy * 0.14 + high * 0.22);
        ctx.fillStyle = `rgba(${120 + Math.floor(front * 90)},${215 + Math.floor(front * 38)},255,${alpha})`;
        ctx.beginPath();
        ctx.arc(px, py, size, 0, Math.PI * 2);
        ctx.fill();
      }

      const inner = ctx.createRadialGradient(cx - base * 0.09, cy - base * 0.12, 0, cx, cy, base * 0.78);
      inner.addColorStop(0, `rgba(224,253,255,${0.13 + energy * 0.16 + bass * 0.09})`);
      inner.addColorStop(0.22, `rgba(80,230,255,${0.06 + energy * 0.09})`);
      inner.addColorStop(0.58, `rgba(22,165,215,${0.02 + mid * 0.04})`);
      inner.addColorStop(1, 'rgba(0,110,165,0)');
      ctx.fillStyle = inner;
      ctx.beginPath();
      ctx.arc(cx, cy, base * (0.78 + bass * 0.06), 0, Math.PI * 2);
      ctx.fill();
      ctx.globalCompositeOperation = 'source-over';

      raf = requestAnimationFrame(render);
    };

    resize();
    window.addEventListener('resize', resize);
    window.addEventListener('pointermove', onPointerMove);
    raf = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('resize', resize);
      window.removeEventListener('pointermove', onPointerMove);
    };
  }, [audioBandsRef, audioLevelRef, visualStateRef]);

  return <canvas id="space" ref={canvasRef} />;
}

export default function App() {
  const [mode, setMode] = useState('IDLE');
  const [reply, setReply] = useState('');
  const [message, setMessage] = useState('');
  const [hint, setHint] = useState('Premi il microfono: il core reagirà in tempo reale alla tua voce.');
  const [online, setOnline] = useState('INITIALIZING');
  const [model, setModel] = useState('LOCAL CORE');
  const [clock, setClock] = useState('00:00:00');
  const [micActive, setMicActive] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [bootVisible, setBootVisible] = useState(true);

  const visualStateRef = useRef('IDLE');
  const audioLevelRef = useRef(0);
  const audioBandsRef = useRef({ bass: 0, mid: 0, high: 0 });
  const mediaStreamRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const audioDataRef = useRef(null);
  const micRafRef = useRef(0);

  const particleCount = useMemo(() => (3400 + 920).toLocaleString('it-IT'), []);

  const changeMode = (next) => {
    const normalized = String(next || 'IDLE').toUpperCase();
    visualStateRef.current = normalized;
    setMode(normalized);
  };

  useEffect(() => {
    const timer = setInterval(() => setClock(new Date().toLocaleTimeString('it-IT', { hour12: false })), 1000);
    const bootTimer = setTimeout(() => setBootVisible(false), 1500);

    const health = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/health`);
        const data = await response.json();
        setOnline(data.ok ? 'JARVIS ONLINE' : 'LM STUDIO OFFLINE');
        setModel(data.models?.[0] ? data.models[0].slice(0, 42) : 'NO MODEL');
      } catch {
        setOnline('BACKEND OFFLINE');
        setModel('LOCAL CORE');
      }
    };

    health();
    const healthTimer = setInterval(health, 12000);
    return () => {
      clearInterval(timer);
      clearInterval(healthTimer);
      clearTimeout(bootTimer);
    };
  }, []);

  useEffect(() => () => {
    cancelAnimationFrame(micRafRef.current);
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    audioContextRef.current?.close();
  }, []);

  const averageBand = (data, from, to) => {
    let total = 0;
    let count = 0;
    const end = Math.min(to, data.length);
    for (let i = Math.max(0, from); i < end; i += 1) {
      total += data[i];
      count += 1;
    }
    return count ? total / (count * 255) : 0;
  };

  const monitorMicrophone = () => {
    const analyser = analyserRef.current;
    const data = audioDataRef.current;
    if (!analyser || !data) return;
    analyser.getByteFrequencyData(data);

    const bassRaw = averageBand(data, 2, 28);
    const midRaw = averageBand(data, 28, 105);
    const highRaw = averageBand(data, 105, 230);
    const previous = audioBandsRef.current;
    const smooth = (oldValue, nextValue, attack = 0.32, release = 0.1) => oldValue + (nextValue - oldValue) * (nextValue > oldValue ? attack : release);
    const bands = {
      bass: smooth(previous.bass, bassRaw, 0.35, 0.08),
      mid: smooth(previous.mid, midRaw, 0.31, 0.09),
      high: smooth(previous.high, highRaw, 0.27, 0.11),
    };
    audioBandsRef.current = bands;

    const raw = bands.bass * 0.44 + bands.mid * 0.38 + bands.high * 0.18;
    const next = audioLevelRef.current + (raw - audioLevelRef.current) * (raw > audioLevelRef.current ? 0.34 : 0.1);
    audioLevelRef.current = next;
    setAudioLevel(next);
    micRafRef.current = requestAnimationFrame(monitorMicrophone);
  };

  const stopMicrophone = () => {
    cancelAnimationFrame(micRafRef.current);
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    audioContextRef.current?.close();
    mediaStreamRef.current = null;
    audioContextRef.current = null;
    analyserRef.current = null;
    audioDataRef.current = null;
    audioLevelRef.current = 0;
    audioBandsRef.current = { bass: 0, mid: 0, high: 0 };
    setAudioLevel(0);
    setMicActive(false);
    setHint('Premi il microfono: il core reagirà in tempo reale alla tua voce.');
    changeMode('IDLE');
  };

  const toggleMicrophone = async () => {
    if (micActive) {
      stopMicrophone();
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioContextCtor();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.68;
      source.connect(analyser);
      mediaStreamRef.current = stream;
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      audioDataRef.current = new Uint8Array(analyser.frequencyBinCount);
      setMicActive(true);
      setHint('Ti sto ascoltando — voce, frequenze e intensità stanno pilotando il core.');
      changeMode('LISTENING');
      monitorMicrophone();
    } catch (error) {
      setReply(`Microfono non disponibile: ${error.message}`);
      changeMode('ERROR');
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;
    setMessage('');
    setReply('');
    setHint('Elaborazione della richiesta…');
    changeMode('THINKING');

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Errore durante la richiesta');
      setReply(data.reply || '');
      if (data.model) setModel(data.model);
      changeMode(data.state || 'SPEAKING');
      setHint('Risposta completata.');
      setTimeout(() => {
        if (!mediaStreamRef.current) {
          changeMode('IDLE');
          setHint('Premi il microfono: il core reagirà in tempo reale alla tua voce.');
        }
      }, 2200);
    } catch (error) {
      setReply(error.message);
      setHint('Controlla il backend e LM Studio.');
      changeMode('ERROR');
    }
  };

  return (
    <div className="jarvis-app">
      <JarvisCanvas visualStateRef={visualStateRef} audioLevelRef={audioLevelRef} audioBandsRef={audioBandsRef} />
      <div className="vignette" />
      <div className="scanlines" />
      <div className="hud">
        <div className="corner tl" /><div className="corner tr" /><div className="corner bl" /><div className="corner br" />
        <div className="topbar">
          <div className="brand">J.A.R.V.I.S.<small>JUST A RATHER VERY INTELLIGENT SYSTEM</small></div>
          <div className="system"><b>{online}</b><br /><span>{clock}</span><br /><span>{model}</span></div>
        </div>
        <div className="side left">
          <Metric label="NEURAL INTERFACE" value="ACTIVE" />
          <Metric label="PARTICLE FIELD" value={particleCount} />
          <Metric label="AUDIO REACTOR" value={audioLevel.toFixed(2)} />
        </div>
        <div className="side right">
          <Metric label="CORE STABILITY" value="99.8%" right />
          <Metric label="RENDER LOOP" value="REALTIME" right />
          <Metric label="VOICE LINK" value={micActive ? 'LIVE' : 'STANDBY'} right />
        </div>
        <div className="center-ui">
          <div className="state">{mode}</div>
          <div className="hint">{hint}</div>
          <div className="reply">{reply}</div>
          <div className="controls">
            <form className="command" onSubmit={submit}>
              <input value={message} onChange={(event) => setMessage(event.target.value)} autoComplete="off" placeholder="Parla con Jarvis…" />
              <button className="send" aria-label="Invia" type="submit">→</button>
            </form>
            <button className={`mic ${micActive ? 'active' : ''}`} onClick={toggleMicrophone} aria-label="Microfono" type="button">◉</button>
          </div>
        </div>
      </div>
      {bootVisible && <div className="boot"><div className="boot-inner"><div className="boot-logo">JARVIS</div><div className="boot-line" /><div className="boot-text">INITIALIZING PARTICLE INTELLIGENCE CORE</div></div></div>}
    </div>
  );
}

function Metric({ label, value, right = false }) {
  return <div className={`metric ${right ? 'metric-right' : ''}`}>{label} <span>{value}</span><div className="meter"><i /></div></div>;
}
