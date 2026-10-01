import React, { useCallback, useEffect, useRef, useState } from 'react';
import JarvisCore from './JarvisCore';

const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const WEBGL_PARTICLE_COUNT = 28000;

function Metric({ label, value }) {
  return (
    <div className="metric">
      {label} <span>{value}</span>
      <div className="meter"><i /></div>
    </div>
  );
}

function isFreeProviderRateLimit(message) {
  const value = String(message || '').toLowerCase();
  return value.includes('429') || value.includes('too many requests') || value.includes('rate limit');
}

export default function App() {
  const [mode, setMode] = useState('INITIALIZING');
  const [reply, setReply] = useState('');
  const [hint, setHint] = useState('');
  const [online, setOnline] = useState('INITIALIZING');
  const [model, setModel] = useState('LOCAL CORE');
  const [clock, setClock] = useState('00:00:00');
  const [voiceLabel, setVoiceLabel] = useState('VOICE PENDING');
  const [audioLevel] = useState(0);
  const [bootVisible, setBootVisible] = useState(true);

  const visualStateRef = useRef('THINKING');
  const audioLevelRef = useRef(0);
  const audioBandsRef = useRef({ bass: 0, mid: 0, high: 0 });
  const chatAbortRef = useRef(null);

  const particleCount = WEBGL_PARTICLE_COUNT.toLocaleString('it-IT');

  const changeMode = useCallback((next) => {
    const normalized = String(next || 'IDLE').toUpperCase();
    visualStateRef.current = normalized;
    setMode(normalized);
  }, []);

  const sendVoiceMessage = useCallback(async (rawText) => {
    const text = String(rawText || '').trim();
    if (!text) return;

    if (chatAbortRef.current) chatAbortRef.current.abort();
    const controller = new AbortController();
    chatAbortRef.current = controller;

    setReply('');
    setHint('');
    changeMode('THINKING');
    window.dispatchEvent(new CustomEvent('jarvis:reply-start', { detail: { query: text } }));

    let answer = '';
    try {
      const response = await fetch(`${API_BASE}/api/realtime/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text }),
        signal: controller.signal,
        cache: 'no-store',
      });
      if (!response.ok) {
        let detail = `Errore realtime ${response.status}`;
        try {
          const data = await response.json();
          detail = data.detail || detail;
        } catch {
          // Keep HTTP fallback detail.
        }
        throw new Error(detail);
      }

      const reader = response.body?.getReader?.();
      if (!reader) throw new Error('Streaming AI non supportato dal browser.');
      const decoder = new TextDecoder();
      let pending = '';

      const consumeLine = (line) => {
        const raw = String(line || '').trim();
        if (!raw) return;
        const event = JSON.parse(raw);
        if (event.type === 'delta') {
          const delta = String(event.text || '');
          if (!delta) return;
          answer += delta;
          setReply(answer.trimStart());
          window.dispatchEvent(new CustomEvent('jarvis:reply-delta', { detail: { text: delta } }));
          return;
        }
        if (event.type === 'done') {
          if (event.model) setModel(String(event.model).slice(0, 48));
          return;
        }
        if (event.type === 'error') throw new Error(event.detail || 'Il cervello AI non è disponibile.');
      };

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        pending += decoder.decode(value, { stream: true });
        const lines = pending.split('\n');
        pending = lines.pop() || '';
        for (const line of lines) consumeLine(line);
      }
      pending += decoder.decode();
      if (pending.trim()) consumeLine(pending);

      if (!answer.trim()) throw new Error('JARVIS non ha prodotto una risposta.');
      window.dispatchEvent(new CustomEvent('jarvis:reply-done', { detail: { text: answer.trim() } }));
    } catch (error) {
      if (error?.name === 'AbortError') return;
      window.dispatchEvent(new CustomEvent('jarvis:reply-error', { detail: { message: error?.message || '' } }));
      const message = error?.message || 'Il cervello AI non è disponibile.';
      setReply('');
      if (isFreeProviderRateLimit(message)) {
        setHint('Il provider AI gratuito ha raggiunto il limite temporaneo.');
        changeMode('WAITING');
      } else {
        setHint(message);
        changeMode('ERROR');
      }
    } finally {
      if (chatAbortRef.current === controller) chatAbortRef.current = null;
    }
  }, [changeMode]);

  useEffect(() => {
    const onVoiceInput = (event) => sendVoiceMessage(event?.detail?.text || '');
    const onBargeIn = () => {
      if (chatAbortRef.current) chatAbortRef.current.abort();
      chatAbortRef.current = null;
      setReply('');
      setHint('');
      changeMode('LISTENING');
    };
    window.addEventListener('jarvis:voice-input', onVoiceInput);
    window.addEventListener('jarvis:barge-in', onBargeIn);
    return () => {
      window.removeEventListener('jarvis:voice-input', onVoiceInput);
      window.removeEventListener('jarvis:barge-in', onBargeIn);
    };
  }, [changeMode, sendVoiceMessage]);

  useEffect(() => {
    const onVoiceState = (event) => {
      const state = String(event?.detail?.state || '').toLowerCase();
      if (state === 'listening') {
        changeMode('LISTENING');
        setHint('');
      } else if (state === 'submitted') {
        changeMode('THINKING');
        setHint('');
      } else if (state === 'speaking') {
        changeMode('SPEAKING');
        setHint('');
      } else if (state === 'blocked' || state === 'permission-needed') {
        changeMode('WAITING');
        setHint('Consenta il microfono a localhost una sola volta.');
      } else if (state === 'unsupported') {
        changeMode('WAITING');
        setHint('La modalità voce fluida richiede Chrome o Edge aggiornato.');
      } else if (state === 'recognition-error') {
        setHint('Riconoscimento vocale momentaneamente non disponibile. Riprovo automaticamente.');
      } else if (state === 'voice-error') {
        changeMode('ERROR');
        setHint(event?.detail?.detail || 'CosyVoice non è disponibile.');
      }
    };

    window.addEventListener('jarvis:voice-state', onVoiceState);
    return () => window.removeEventListener('jarvis:voice-state', onVoiceState);
  }, [changeMode]);

  useEffect(() => {
    const updateClock = () => setClock(new Date().toLocaleTimeString('it-IT', { hour12: false }));
    updateClock();
    const timer = setInterval(updateClock, 1000);
    const bootTimer = setTimeout(() => setBootVisible(false), 1100);

    const health = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/health`, { cache: 'no-store' });
        const data = await response.json();
        setOnline(data.ok ? 'JARVIS ONLINE' : 'AI FALLBACK');
        const active = data.active_model || data.models?.[0];
        const provider = data.provider ? `${data.provider} · ` : '';
        setModel(active ? `${provider}${active}`.slice(0, 48) : 'LOCAL CORE');

        const voice = data.voice || data.cloud_tts || {};
        if (voice.provider === 'cosyvoice3-local') {
          setVoiceLabel(voice.ready ? 'COSYVOICE REALTIME' : 'VOICE PENDING');
        } else if (voice.enabled && voice.provider) {
          setVoiceLabel(String(voice.provider).toUpperCase().slice(0, 22));
        } else {
          setVoiceLabel('VOICE PENDING');
        }
      } catch {
        setOnline('BACKEND OFFLINE');
        setModel('LOCAL CORE');
        setVoiceLabel('VOICE PENDING');
      }
    };

    health();
    const healthTimer = setInterval(health, 30000);
    return () => {
      clearInterval(timer);
      clearInterval(healthTimer);
      clearTimeout(bootTimer);
      if (chatAbortRef.current) chatAbortRef.current.abort();
    };
  }, []);

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
          <Metric label="VOICE LINK" value={voiceLabel} />
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
            <div className="boot-text">INITIALIZING JARVIS REALTIME CORE</div>
          </div>
        </div>
      )}
    </div>
  );
}
