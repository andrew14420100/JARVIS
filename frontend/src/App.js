import React, { useCallback, useEffect, useRef, useState } from 'react';
import JarvisCore from './JarvisCore';

const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const WEBGL_PARTICLE_COUNT = 28000;

function greetingForNow() {
  const hour = new Date().getHours();
  if (hour < 12) return 'Buongiorno, signore. Come sta oggi?';
  if (hour < 18) return 'Buon pomeriggio, signore. Come sta andando la giornata?';
  return 'Buonasera, signore. È un piacere rivederla. Come sta?';
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
  const [mode, setMode] = useState('SPEAKING');
  const [reply, setReply] = useState(() => greetingForNow());
  const [hint, setHint] = useState('JARVIS è online. La conversazione è vocale.');
  const [online, setOnline] = useState('INITIALIZING');
  const [model, setModel] = useState('CLOUD CORE');
  const [clock, setClock] = useState('00:00:00');
  const [localVoiceActive, setLocalVoiceActive] = useState(false);
  const [localRuntimeState, setLocalRuntimeState] = useState('IDLE');
  const [audioLevel] = useState(0);
  const [bootVisible, setBootVisible] = useState(true);

  const visualStateRef = useRef('SPEAKING');
  const audioLevelRef = useRef(0);
  const audioBandsRef = useRef({ bass: 0, mid: 0, high: 0 });
  const runtimePauseUntilRef = useRef(0);
  const greetingRef = useRef(reply);

  const particleCount = WEBGL_PARTICLE_COUNT.toLocaleString('it-IT');

  const changeMode = useCallback((next) => {
    const normalized = String(next || 'IDLE').toUpperCase();
    visualStateRef.current = normalized;
    setMode(normalized);
  }, []);

  const sendVoiceMessage = useCallback(async (rawText) => {
    const text = String(rawText || '').trim();
    if (!text) return;

    runtimePauseUntilRef.current = Date.now() + 30000;
    setReply('');
    setHint('Un momento, signore…');
    changeMode('THINKING');

    try {
      const response = await fetch(`${API_BASE}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || 'Errore durante la richiesta');

      const answer = String(data.reply || '').trim() || 'Sono qui, signore.';
      setReply(answer);
      if (data.model) setModel(String(data.model).slice(0, 48));
      changeMode('SPEAKING');
      setHint('');
      window.dispatchEvent(new CustomEvent('jarvis:reply-ready', { detail: { text: answer } }));
      runtimePauseUntilRef.current = Date.now() + 4000;
    } catch (error) {
      const message = error?.message || 'Il cervello cloud non è disponibile.';
      setReply(message);
      setHint('Non riesco a raggiungere il cervello AI in questo momento.');
      changeMode('ERROR');
      runtimePauseUntilRef.current = Date.now() + 4000;
    }
  }, [changeMode]);

  useEffect(() => {
    const onVoiceInput = (event) => sendVoiceMessage(event?.detail?.text || '');
    window.addEventListener('jarvis:voice-input', onVoiceInput);
    return () => window.removeEventListener('jarvis:voice-input', onVoiceInput);
  }, [sendVoiceMessage]);

  useEffect(() => {
    const updateClock = () => setClock(new Date().toLocaleTimeString('it-IT', { hour12: false }));
    updateClock();
    const timer = setInterval(updateClock, 1000);
    const bootTimer = setTimeout(() => setBootVisible(false), 1550);
    const greetTimer = setTimeout(() => {
      window.dispatchEvent(new CustomEvent('jarvis:greeting', { detail: { text: greetingRef.current } }));
    }, 450);

    const health = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/health`);
        const data = await response.json();
        setOnline(data.ok ? 'JARVIS ONLINE' : 'CLOUD AI OFFLINE');
        const active = data.active_model || data.models?.[0];
        const provider = data.provider ? `${data.provider} · ` : '';
        setModel(active ? `${provider}${active}`.slice(0, 48) : 'NO FREE MODEL');
      } catch {
        setOnline('BACKEND OFFLINE');
        setModel('CLOUD CORE');
      }
    };

    health();
    const healthTimer = setInterval(health, 12000);
    return () => {
      clearInterval(timer);
      clearInterval(healthTimer);
      clearTimeout(bootTimer);
      clearTimeout(greetTimer);
    };
  }, []);

  useEffect(() => {
    let disposed = false;

    const syncRuntimeState = async () => {
      if (disposed || Date.now() < runtimePauseUntilRef.current) return;
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
          setHint(`Conferma richiesta per ${data.pending_confirmation}.`);
        } else if (next === 'LISTENING') {
          setHint('La ascolto, signore.');
        } else if (next === 'THINKING') {
          setHint('Sto valutando la richiesta…');
        } else if (next === 'EXECUTING') {
          setHint('Sto procedendo.');
        } else if (next === 'SPEAKING') {
          setHint('');
        } else if (next === 'IDLE') {
          setHint('In attesa, signore.');
        }
      } catch {
        // Il runtime desktop è opzionale nella preview web.
      }
    };

    syncRuntimeState();
    const stateTimer = setInterval(syncRuntimeState, 600);
    return () => {
      disposed = true;
      clearInterval(stateTimer);
    };
  }, []);

  const voiceLink = localVoiceActive
    ? (localRuntimeState === 'IDLE' ? 'LOCAL READY' : localRuntimeState)
    : 'VOICE FIRST';

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

        <div className="center-ui voice-only">
          <div className="state">{mode}</div>
          <div className="hint">{hint}</div>
          <div className="reply">{reply}</div>
        </div>
      </div>

      {bootVisible && (
        <div className="boot">
          <div className="boot-inner">
            <div className="boot-logo">JARVIS</div>
            <div className="boot-line" />
            <div className="boot-text">INITIALIZING JARVIS COGNITIVE CORE</div>
          </div>
        </div>
      )}
    </div>
  );
}
