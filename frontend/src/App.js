import React, { useEffect, useMemo, useRef, useState } from 'react';

const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');

function JarvisCanvas({ visualStateRef, audioLevelRef }) {
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
    let energy = 0.16;
    let rotation = 0;
    let rotX = 0;
    let mouseX = 0;
    let mouseY = 0;

    const CORE_COUNT = 2400;
    const DUST_COUNT = 760;
    const core = [];
    const dust = [];
    const golden = Math.PI * (3 - Math.sqrt(5));

    for (let i = 0; i < CORE_COUNT; i += 1) {
      const y = 1 - (i / (CORE_COUNT - 1)) * 2;
      const r = Math.sqrt(1 - y * y);
      const theta = golden * i;
      const shell = 0.83 + Math.random() * 0.28;
      core.push({
        x: Math.cos(theta) * r * shell,
        y: y * shell,
        z: Math.sin(theta) * r * shell,
        size: 0.42 + Math.random() * 1.1,
        phase: Math.random() * Math.PI * 2,
        alpha: 0.3 + Math.random() * 0.7,
      });
    }

    for (let i = 0; i < DUST_COUNT; i += 1) {
      dust.push({
        angle: Math.random() * Math.PI * 2,
        radius: 0.95 + Math.pow(Math.random(), 0.42) * 2.4,
        z: (Math.random() - 0.5) * 2.8,
        speed: (0.025 + Math.random() * 0.13) * (Math.random() < 0.5 ? -1 : 1),
        size: 0.35 + Math.random() * 1.05,
        alpha: 0.08 + Math.random() * 0.42,
        phase: Math.random() * Math.PI * 2,
      });
    }

    const resize = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 1.65);
      width = window.innerWidth;
      height = window.innerHeight;
      cx = width * 0.5;
      cy = height * 0.47;
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

    const drawRing = (radius, tilt, ringRotation, alpha, dash = 0) => {
      ctx.save();
      ctx.translate(cx, cy);
      ctx.rotate(ringRotation);
      ctx.scale(1, tilt);
      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      ctx.strokeStyle = `rgba(82,216,245,${alpha})`;
      ctx.lineWidth = 0.7;
      if (dash) ctx.setLineDash([dash, dash * 1.7]);
      ctx.stroke();
      ctx.restore();
    };

    const stateEnergy = {
      IDLE: 0.16,
      LISTENING: 0.5,
      THINKING: 0.82,
      EXECUTING: 0.98,
      SPEAKING: 0.68,
      ERROR: 0.3,
    };

    const render = (now) => {
      const dt = Math.min((now - lastFrame) / 1000, 0.05);
      lastFrame = now;
      const audio = audioLevelRef.current || 0;
      const visualState = visualStateRef.current || 'IDLE';
      const targetEnergy = (stateEnergy[visualState] ?? 0.2) + audio * 0.78;
      energy += (Math.min(targetEnergy, 1.35) - energy) * 0.075;
      const t = now * 0.001;
      const base = Math.min(width, height) * (width < 700 ? 0.175 : 0.19);

      const background = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(width, height) * 0.74);
      background.addColorStop(0, `rgb(${2 + Math.floor(energy * 3)},${12 + Math.floor(energy * 8)},${18 + Math.floor(energy * 12)})`);
      background.addColorStop(0.35, '#02080c');
      background.addColorStop(1, '#010305');
      ctx.fillStyle = background;
      ctx.fillRect(0, 0, width, height);

      rotation += dt * (0.11 + energy * 0.24);
      rotX += (mouseY * 0.11 + 0.08 * Math.sin(t * 0.21) - rotX) * 0.018;
      const rotY = rotation + mouseX * 0.13;

      const glow = ctx.createRadialGradient(cx, cy, base * 0.1, cx, cy, base * (1.15 + energy * 0.18));
      glow.addColorStop(0, `rgba(112,235,255,${0.08 + energy * 0.09})`);
      glow.addColorStop(0.42, `rgba(24,184,222,${0.035 + energy * 0.04})`);
      glow.addColorStop(1, 'rgba(0,90,130,0)');
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(cx, cy, base * 1.45, 0, Math.PI * 2);
      ctx.fill();

      drawRing(base * 1.18, 0.28, t * 0.08, 0.12 + energy * 0.04, 5);
      drawRing(base * 1.38, 0.58, -t * 0.052, 0.08 + energy * 0.035, 12);
      drawRing(base * 1.57, 0.86, t * 0.03, 0.05 + energy * 0.025, 3);

      ctx.globalCompositeOperation = 'lighter';

      for (const p of dust) {
        p.angle += p.speed * dt * (1 + energy * 2.1);
        const pulse = Math.sin(t * (0.55 + Math.abs(p.speed) * 2) + p.phase);
        const rr = p.radius * (1 + audio * 0.08 * pulse);
        const x = Math.cos(p.angle) * rr;
        const z = Math.sin(p.angle) * rr;
        const y = p.z * 0.55 + Math.sin(p.angle * 1.7 + p.phase) * 0.12;
        const q = rotatePoint(x, y, z, rotX * 0.35, rotY * 0.28);
        const depth = 3.8 + q[2];
        if (depth <= 0.2) continue;
        const persp = 3.3 / depth;
        const px = cx + q[0] * base * 0.72 * persp;
        const py = cy + q[1] * base * 0.72 * persp;
        const alpha = p.alpha * (0.32 + energy * 0.58) * (0.55 + 0.45 * Math.sin(t * 1.8 + p.phase));
        ctx.fillStyle = `rgba(83,220,255,${Math.max(0, Math.min(alpha, 0.72))})`;
        ctx.fillRect(px, py, p.size * (0.7 + persp * 0.5), p.size * (0.7 + persp * 0.5));
      }

      for (const p of core) {
        const n1 = Math.sin(p.x * 5.7 + p.y * 2.4 + t * (0.72 + energy * 0.55) + p.phase);
        const n2 = Math.cos(p.z * 6.1 - p.x * 3.2 - t * 0.47 + p.phase * 0.4);
        const voiceWave = Math.sin((p.y + 1) * 9 - t * 7.5 + p.phase * 0.12) * audio;
        const distortion = 1 + n1 * (0.015 + energy * 0.045) + n2 * (0.008 + energy * 0.026) + voiceWave * 0.075;
        const q = rotatePoint(p.x * distortion, p.y * distortion, p.z * distortion, rotX, rotY);
        const depth = 3.2 + q[2];
        if (depth <= 0.15) continue;
        const persp = 2.8 / depth;
        const breathe = 1 + Math.sin(t * 1.45) * 0.012 + audio * 0.085;
        const px = cx + q[0] * base * persp * breathe;
        const py = cy + q[1] * base * persp * breathe;
        const front = Math.max(0.08, Math.min((q[2] + 1.25) / 2.5, 1));
        const edge = Math.max(0.2, Math.min(1 - Math.abs(q[2]) * 0.2, 1));
        const flicker = 0.78 + 0.22 * Math.sin(t * (2.1 + energy * 4) + p.phase);
        const alpha = Math.max(0.04, Math.min(p.alpha * front * edge * flicker * (0.56 + energy * 0.42), 0.98));
        const size = p.size * (0.7 + persp * 0.85) * (1 + energy * 0.18);
        ctx.fillStyle = `rgba(${125 + Math.floor(front * 80)},${220 + Math.floor(front * 30)},255,${alpha})`;
        ctx.beginPath();
        ctx.arc(px, py, size, 0, Math.PI * 2);
        ctx.fill();
      }

      const inner = ctx.createRadialGradient(cx - base * 0.08, cy - base * 0.11, 0, cx, cy, base * 0.72);
      inner.addColorStop(0, `rgba(210,251,255,${0.12 + energy * 0.14})`);
      inner.addColorStop(0.25, `rgba(61,220,255,${0.055 + energy * 0.08})`);
      inner.addColorStop(1, 'rgba(0,125,180,0)');
      ctx.fillStyle = inner;
      ctx.beginPath();
      ctx.arc(cx, cy, base * 0.8 * (1 + audio * 0.06), 0, Math.PI * 2);
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
  }, [audioLevelRef, visualStateRef]);

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
  const mediaStreamRef = useRef(null);
  const audioContextRef = useRef(null);
  const analyserRef = useRef(null);
  const audioDataRef = useRef(null);
  const micRafRef = useRef(0);

  const particleCount = useMemo(() => (2400 + 760).toLocaleString('it-IT'), []);

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
    return () => {
      clearInterval(timer);
      clearTimeout(bootTimer);
    };
  }, []);

  useEffect(() => () => {
    cancelAnimationFrame(micRafRef.current);
    mediaStreamRef.current?.getTracks().forEach((track) => track.stop());
    audioContextRef.current?.close();
  }, []);

  const monitorMicrophone = () => {
    const analyser = analyserRef.current;
    const data = audioDataRef.current;
    if (!analyser || !data) return;
    analyser.getByteFrequencyData(data);
    let weighted = 0;
    let total = 0;
    const max = Math.min(data.length, 180);
    for (let i = 2; i < max; i += 1) {
      const weight = i < 36 ? 1.45 : i < 90 ? 1 : 0.7;
      weighted += data[i] * weight;
      total += 255 * weight;
    }
    const raw = total ? weighted / total : 0;
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
      analyser.fftSize = 1024;
      analyser.smoothingTimeConstant = 0.72;
      source.connect(analyser);
      mediaStreamRef.current = stream;
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      audioDataRef.current = new Uint8Array(analyser.frequencyBinCount);
      setMicActive(true);
      setHint('Ti sto ascoltando — il campo particellare segue la tua voce.');
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
      <JarvisCanvas visualStateRef={visualStateRef} audioLevelRef={audioLevelRef} />
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
          <Metric label="RENDER LOOP" value="GPU ACTIVE" right />
          <Metric label="VOICE LINK" value={micActive ? 'LIVE' : 'STANDBY'} right />
        </div>
        <div className="center-ui">
          <div className="state">{mode}</div>
          <div className="hint">{hint}</div>
          <div className="reply">{reply}</div>
          <div className="controls">
            <form className="command" onSubmit={submit}>
              <input value={message} onChange={(e) => setMessage(e.target.value)} autoComplete="off" placeholder="Parla con Jarvis…" />
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
