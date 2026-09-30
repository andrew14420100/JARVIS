import React, { useEffect, useRef, useState } from 'react';
import JarvisCore from './JarvisCore';

const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const WEBGL_PARTICLE_COUNT = 28000;

function averageBand(data, from, to) {
  let total = 0;
  let count = 0;
  const end = Math.min(to, data.length);
  for (let i = Math.max(0, from); i < end; i += 1) {
    total += data[i];
    count += 1;
  }
  return count ? total / (count * 255) : 0;
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      {label} <span>{value}</span>
      <div className="meter"><i /></div>
    </div>
  );
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
  const [localVoiceActive, setLocalVoiceActive] = useState(false);
  const [localRuntimeState, setLocalRuntimeState] = useState('IDLE');
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
  const runtimePauseUntilRef = useRef(0);

  const particleCount = WEBGL_PARTICLE_COUNT.toLocaleString('it-IT');

  const changeMode = (next) => {
    const normalized = String(next || 'IDLE').toUpperCase();
    visualStateRef.current = normalized;
    setMode(normalized);
  };

  useEffect(() => {
    const updateClock = () => setClock(new Date().toLocaleTimeString('it-IT', { hour12: false }));
    updateClock();
    const timer = setInterval(updateClock, 1000);
    const bootTimer = setTimeout(() => setBootVisible(false), 1550);

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

  useEffect(() => {
    let disposed = false;

    const syncRuntimeState = async () => {
      if (disposed || mediaStreamRef.current || Date.now() < runtimePauseUntilRef.current) return;
      try {
        const response = await fetch(`${API_BASE}/api/state`, { cache: 'no-store' });
        if (!response.ok) return;
        const data = await response.json();
        const voiceEnabled = Boolean(data.voice_enabled);
        const next = String(data.state || 'IDLE').toUpperCase();
        setLocalVoiceActive(voiceEnabled);
        setLocalRuntimeState(next);

        if (!voiceEnabled) return;
        visualStateRef.current = next;
        setMode(next);

        if (data.pending_confirmation) {
          setHint(`Conferma richiesta per: ${data.pending_confirmation}. Di' “confermo” oppure “annulla”.`);
        } else if (next === 'LISTENING') {
          setHint('Wake word rilevata — Jarvis ti sta ascoltando.');
        } else if (next === 'THINKING') {
          setHint('Jarvis sta elaborando la richiesta con il modello locale…');
        } else if (next === 'EXECUTING') {
          setHint('Jarvis sta usando uno strumento locale…');
        } else if (next === 'SPEAKING') {
          setHint('Jarvis sta rispondendo.');
        } else if (next === 'IDLE') {
          setHint('Di’ “Hey Jarvis” oppure scrivi una richiesta.');
        }
      } catch {
        // Runtime sync is optional; health status already reports backend failures.
      }
    };

    syncRuntimeState();
    const stateTimer = setInterval(syncRuntimeState, 300);
    return () => {
      disposed = true;
      clearInterval(stateTimer);
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
    const bassRaw = averageBand(data, 2, 28);
    const midRaw = averageBand(data, 28, 105);
    const highRaw = averageBand(data, 105, 230);
    const previous = audioBandsRef.current;
    const smooth = (oldValue, nextValue, attack, release) => (
      oldValue + (nextValue - oldValue) * (nextValue > oldValue ? attack : release)
    );

    const bands = {
      bass: smooth(previous.bass, bassRaw, 0.37, 0.075),
      mid: smooth(previous.mid, midRaw, 0.32, 0.085),
      high: smooth(previous.high, highRaw, 0.29, 0.105),
    };
    audioBandsRef.current = bands;

    const raw = bands.bass * 0.46 + bands.mid * 0.37 + bands.high * 0.17;
    const next = audioLevelRef.current + (raw - audioLevelRef.current) * (raw > audioLevelRef.current ? 0.36 : 0.09);
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
    setHint(localVoiceActive ? 'Di’ “Hey Jarvis” oppure scrivi una richiesta.' : 'Premi il microfono: il core reagirà in tempo reale alla tua voce.');
    changeMode('IDLE');
  };

  const toggleMicrophone = async () => {
    if (micActive) {
      stopMicrophone();
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
      const audioContext = new AudioContextCtor();
      await audioContext.resume();
      const source = audioContext.createMediaStreamSource(stream);
      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.66;
      source.connect(analyser);

      mediaStreamRef.current = stream;
      audioContextRef.current = audioContext;
      analyserRef.current = analyser;
      audioDataRef.current = new Uint8Array(analyser.frequencyBinCount);
      setMicActive(true);
      setHint('Ti sto ascoltando — bassi, medi e alti stanno pilotando il core GPU.');
      changeMode('LISTENING');
      monitorMicrophone();
    } catch (error) {
      setReply(`Microfono non disponibile: ${error.message}`);
      setHint('Il browser non ha concesso l’accesso al microfono.');
      changeMode('ERROR');
    }
  };

  const submit = async (event) => {
    event.preventDefault();
    const text = message.trim();
    if (!text) return;

    runtimePauseUntilRef.current = Date.now() + 15000;
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
      runtimePauseUntilRef.current = Date.now() + 2300;

      setTimeout(() => {
        if (!mediaStreamRef.current) {
          changeMode('IDLE');
          setHint(localVoiceActive ? 'Di’ “Hey Jarvis” oppure scrivi una richiesta.' : 'Premi il microfono: il core reagirà in tempo reale alla tua voce.');
        }
      }, 2200);
    } catch (error) {
      runtimePauseUntilRef.current = Date.now() + 2300;
      setReply(error.message);
      setHint('Il backend è online, ma il modello locale non è ancora collegato.');
      changeMode('ERROR');
    }
  };

  const voiceLink = micActive
    ? 'BROWSER LIVE'
    : localVoiceActive
      ? (localRuntimeState === 'IDLE' ? 'LOCAL READY' : localRuntimeState)
      : 'STANDBY';

  return (
    <div className="jarvis-app">
      <JarvisCore
        visualStateRef={visualStateRef}
        audioLevelRef={audioLevelRef}
        audioBandsRef={audioBandsRef}
      />
      <div className="core-ambient" aria-hidden="true" />
      <div className="vignette" />
      <div className="scanlines" />

      <div className="hud">
        <div className="corner tl" />
        <div className="corner tr" />
        <div className="corner bl" />
        <div className="corner br" />

        <div className="topbar">
          <div className="brand">
            J.A.R.V.I.S.
            <small>JUST A RATHER VERY INTELLIGENT SYSTEM</small>
          </div>
          <div className="system">
            <b>{online}</b><br />
            <span>{clock}</span><br />
            <span>{model}</span>
          </div>
        </div>

        <div className="side left">
          <Metric label="NEURAL INTERFACE" value="ACTIVE" />
          <Metric label="GPU PARTICLE FIELD" value={particleCount} />
          <Metric label="AUDIO REACTOR" value={audioLevel.toFixed(2)} />
        </div>

        <div className="side right">
          <Metric label="CORE STABILITY" value="99.8%" />
          <Metric label="RENDER LOOP" value="WEBGL2" />
          <Metric label="VOICE LINK" value={voiceLink} />
        </div>

        <div className="center-ui">
          <div className="state">{mode}</div>
          <div className="hint">{hint}</div>
          <div className="reply">{reply}</div>
          <div className="controls">
            <form className="command" onSubmit={submit}>
              <input
                value={message}
                onChange={(event) => setMessage(event.target.value)}
                autoComplete="off"
                placeholder="Parla con Jarvis…"
              />
              <button className="send" aria-label="Invia" type="submit">→</button>
            </form>
            <button
              className={`mic ${micActive ? 'active' : ''}`}
              onClick={toggleMicrophone}
              aria-label="Microfono"
              type="button"
            >
              ◉
            </button>
          </div>
        </div>
      </div>

      {bootVisible && (
        <div className="boot">
          <div className="boot-inner">
            <div className="boot-logo">JARVIS</div>
            <div className="boot-line" />
            <div className="boot-text">INITIALIZING GPU PARTICLE INTELLIGENCE CORE</div>
          </div>
        </div>
      )}
    </div>
  );
}
