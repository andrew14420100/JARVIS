// Stable browser voice bridge for JARVIS.
//
// Contract:
// - "Jarvis" / "Hey Jarvis" activates the session once.
// - After activation the session stays open until an explicit standby command.
// - JARVIS never falls back to a different browser/system voice: if CosyVoice
//   is unavailable, speech stops and the UI reports the voice error.
// - Browser microphone recognition remains optional; the desktop stable runtime
//   is still the preferred path for speaker-ID and stronger anti-echo.

let recognition = null;
let recognitionRunning = false;
let voiceRuntimeStarted = false;
let sessionActive = false;
let speaking = false;
let submitted = false;
let activeAudio = null;
let activeAudioUrl = '';
let pcmContext = null;
let pcmAbortController = null;
let pcmGeneration = 0;
let pendingTurnTimer = null;
let finalBuffer = '';
let interimBuffer = '';
let micStream = null;
let micMonitorContext = null;
let micAnalyser = null;
let micMonitorFrame = 0;
let bargeInSince = 0;
let speechStartedAt = 0;
let retryInstalled = false;
const pcmSources = new Set();

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const RESTART_DELAY_MS = 160;
const TURN_SILENCE_MS = 700;
const BARGE_IN_RMS = 0.055;
const BARGE_IN_HOLD_MS = 220;
const BARGE_IN_GUARD_MS = 650;
const ACTIVATION_PHRASE = 'Sì, signore?';

const STANDBY_PATTERNS = [
  /^(?:jarvis[, ]*)?(?:vai|torna)\s+in\s+standby[.!?]*$/i,
  /^(?:jarvis[, ]*)?chiudi\s+(?:la\s+)?sessione[.!?]*$/i,
  /^(?:jarvis[, ]*)?(?:stop|basta)(?:\s+jarvis)?[.!?]*$/i,
];

function setHint(text) {
  const hint = document.querySelector('.hint');
  if (hint) hint.textContent = text || '';
}

function setVoiceState(state, detail = '') {
  window.dispatchEvent(new CustomEvent('jarvis:voice-state', {
    detail: { state, detail },
  }));
}

function emitVoiceInput(text) {
  const value = String(text || '').trim();
  if (!value) return;
  setVoiceState('submitted', value);
  window.dispatchEvent(new CustomEvent('jarvis:voice-input', { detail: { text: value } }));
}

export function normalizeWakeTranscript(text) {
  const value = String(text || '').trim();
  if (!value) return { activated: false, command: '' };
  const pattern = /\b(?:hey\s+)?jarvis\b[\s,.:;!?-]*/i;
  const match = value.match(pattern);
  if (!match) return { activated: false, command: value };
  const index = match.index || 0;
  const command = `${value.slice(0, index)} ${value.slice(index + match[0].length)}`
    .replace(/\s+/g, ' ')
    .trim();
  return { activated: true, command };
}

export function isStandbyCommand(text) {
  const value = String(text || '').trim();
  return Boolean(value) && STANDBY_PATTERNS.some((pattern) => pattern.test(value));
}

export function routeTranscript(text, active) {
  const value = String(text || '').trim();
  if (!value) return { action: 'ignore', active: Boolean(active), command: '' };
  const parsed = normalizeWakeTranscript(value);

  if (!active) {
    if (!parsed.activated) return { action: 'standby', active: false, command: '' };
    if (!parsed.command) return { action: 'activate', active: true, command: '' };
    return { action: 'submit', active: true, command: parsed.command };
  }

  if (isStandbyCommand(value)) return { action: 'deactivate', active: false, command: '' };
  const command = parsed.activated && parsed.command ? parsed.command : value;
  return { action: 'submit', active: true, command };
}

export function pcm16ToFloat32(bytes) {
  const sampleCount = Math.floor(bytes.byteLength / 2);
  const floats = new Float32Array(sampleCount);
  const view = new DataView(bytes.buffer, bytes.byteOffset, sampleCount * 2);
  for (let index = 0; index < sampleCount; index += 1) {
    const value = view.getInt16(index * 2, true);
    floats[index] = value < 0 ? value / 32768 : value / 32767;
  }
  return floats;
}

function clearPendingTurn() {
  if (pendingTurnTimer) window.clearTimeout(pendingTurnTimer);
  pendingTurnTimer = null;
}

function resetTranscriptBuffers() {
  finalBuffer = '';
  interimBuffer = '';
  clearPendingTurn();
}

function candidateTranscript() {
  return `${finalBuffer} ${interimBuffer}`.replace(/\s+/g, ' ').trim();
}

function stopRecognition() {
  clearPendingTurn();
  if (!recognition) {
    recognitionRunning = false;
    return;
  }
  try {
    recognition.abort();
  } catch {
    // Already closing.
  }
  recognition = null;
  recognitionRunning = false;
}

function stopAudio() {
  pcmGeneration += 1;
  if (pcmAbortController) {
    try {
      pcmAbortController.abort();
    } catch {
      // Request may already be complete.
    }
  }
  pcmAbortController = null;

  for (const source of pcmSources) {
    try {
      source.stop();
    } catch {
      // Source may already have ended.
    }
  }
  pcmSources.clear();

  if (activeAudio) {
    try {
      activeAudio.pause();
      activeAudio.src = '';
    } catch {
      // Ignore cleanup race.
    }
  }
  activeAudio = null;
  if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
  activeAudioUrl = '';
}

function installOneTimeGesture(action) {
  if (retryInstalled) return;
  retryInstalled = true;
  const retry = () => {
    retryInstalled = false;
    document.removeEventListener('pointerdown', retry, true);
    document.removeEventListener('keydown', retry, true);
    action();
  };
  document.addEventListener('pointerdown', retry, true);
  document.addEventListener('keydown', retry, true);
}

async function ensureMicrophoneStream() {
  if (micStream?.active) return true;
  if (!navigator.mediaDevices?.getUserMedia) return false;
  try {
    micStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
      },
    });
    startMicMonitor();
    return true;
  } catch (error) {
    console.warn('[JARVIS] Microphone permission:', error);
    return false;
  }
}

function startMicMonitor() {
  if (!micStream?.active || micMonitorFrame) return;
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) return;
  try {
    micMonitorContext = micMonitorContext || new AudioContextCtor();
    const source = micMonitorContext.createMediaStreamSource(micStream);
    micAnalyser = micMonitorContext.createAnalyser();
    micAnalyser.fftSize = 1024;
    source.connect(micAnalyser);
    const samples = new Float32Array(micAnalyser.fftSize);

    const tick = () => {
      if (!voiceRuntimeStarted || !micAnalyser) {
        micMonitorFrame = 0;
        return;
      }
      micAnalyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let index = 0; index < samples.length; index += 1) sum += samples[index] * samples[index];
      const rms = Math.sqrt(sum / samples.length);
      if (speaking && sessionActive && Date.now() - speechStartedAt > BARGE_IN_GUARD_MS && rms >= BARGE_IN_RMS) {
        if (!bargeInSince) bargeInSince = performance.now();
        if (performance.now() - bargeInSince >= BARGE_IN_HOLD_MS) {
          bargeInSince = 0;
          speaking = false;
          stopAudio();
          resetTranscriptBuffers();
          setVoiceState('listening');
          setHint('La ascolto, signore.');
          startRecognition();
        }
      } else {
        bargeInSince = 0;
      }
      micMonitorFrame = window.requestAnimationFrame(tick);
    };
    micMonitorFrame = window.requestAnimationFrame(tick);
  } catch (error) {
    console.warn('[JARVIS] Microphone monitor:', error);
    micMonitorFrame = 0;
  }
}

function scheduleRecognitionRestart(delay = RESTART_DELAY_MS) {
  if (!voiceRuntimeStarted || recognitionRunning || speaking) return;
  window.setTimeout(() => {
    if (voiceRuntimeStarted && !recognitionRunning && !speaking) startRecognition();
  }, delay);
}

function reopenConversation() {
  speaking = false;
  resetTranscriptBuffers();
  setVoiceState(sessionActive ? 'listening' : 'standby');
  setHint(sessionActive ? 'La ascolto, signore.' : 'In standby. Dica “Jarvis”.');
  if (!recognitionRunning) startRecognition();
}

async function fetchErrorDetail(response, fallback) {
  try {
    const payload = await response.json();
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function getPcmContext() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) throw new Error('Web Audio non supportato dal browser.');
  if (!pcmContext || pcmContext.state === 'closed') pcmContext = new AudioContextCtor();
  if (pcmContext.state === 'suspended') await pcmContext.resume();
  return pcmContext;
}

async function playPcmStream(response) {
  const generation = pcmGeneration;
  const ctx = await getPcmContext();
  const sampleRate = Number(response.headers.get('X-Sample-Rate')) || 24000;
  const reader = response.body?.getReader?.();
  if (!reader) throw new Error('Streaming audio non supportato.');
  let scheduledAt = ctx.currentTime + 0.025;
  let carry = new Uint8Array(0);
  let heardAnything = false;
  speaking = true;
  speechStartedAt = Date.now();
  setVoiceState('speaking');

  while (true) {
    const { value, done } = await reader.read();
    if (done || generation !== pcmGeneration) break;
    if (!value?.byteLength) continue;
    let bytes = value;
    if (carry.byteLength) {
      bytes = new Uint8Array(carry.byteLength + value.byteLength);
      bytes.set(carry, 0);
      bytes.set(value, carry.byteLength);
    }
    const usableLength = bytes.byteLength - (bytes.byteLength % 2);
    carry = usableLength < bytes.byteLength ? bytes.slice(usableLength) : new Uint8Array(0);
    if (!usableLength) continue;
    const floats = pcm16ToFloat32(bytes.subarray(0, usableLength));
    if (!floats.length) continue;
    const buffer = ctx.createBuffer(1, floats.length, sampleRate);
    buffer.copyToChannel(floats, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    pcmSources.add(source);
    source.onended = () => pcmSources.delete(source);
    const startAt = Math.max(scheduledAt, ctx.currentTime + 0.010);
    source.start(startAt);
    scheduledAt = startAt + buffer.duration;
    heardAnything = true;
  }

  if (!heardAnything || generation !== pcmGeneration) {
    if (generation === pcmGeneration) reopenConversation();
    return;
  }
  const remainingMs = Math.max(0, (scheduledAt - ctx.currentTime) * 1000) + 40;
  window.setTimeout(() => {
    if (generation === pcmGeneration) reopenConversation();
  }, remainingMs);
}

async function playGeneratedAudio(blob) {
  stopAudio();
  activeAudioUrl = URL.createObjectURL(blob);
  activeAudio = new Audio(activeAudioUrl);
  activeAudio.preload = 'auto';
  activeAudio.onplaying = () => {
    speaking = true;
    speechStartedAt = Date.now();
    setVoiceState('speaking');
  };
  activeAudio.onended = reopenConversation;
  activeAudio.onerror = reopenConversation;
  await activeAudio.play();
}

async function speakClonedVoice(text, { short = false } = {}) {
  const content = String(text || '').trim();
  if (!content) {
    reopenConversation();
    return;
  }
  stopRecognition();
  stopAudio();
  speaking = true;
  speechStartedAt = Date.now();
  setVoiceState('speaking');

  try {
    const endpoint = short ? '/api/tts' : '/api/tts/stream';
    pcmAbortController = new AbortController();
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: content }),
      signal: pcmAbortController.signal,
    });
    if (!response.ok) throw new Error(await fetchErrorDetail(response, 'Voce clonata non disponibile.'));
    if (!short && response.headers.get('X-Audio-Format') === 'pcm_s16le_mono') {
      await playPcmStream(response);
      return;
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('Audio vuoto.');
    await playGeneratedAudio(blob);
  } catch (error) {
    if (error?.name === 'AbortError') return;
    console.warn('[JARVIS] CosyVoice:', error);
    speaking = false;
    setVoiceState('voice-error', error?.message || 'CosyVoice non disponibile');
    setHint('La voce clonata non è disponibile; JARVIS resta in ascolto senza cambiare voce.');
    reopenConversation();
  }
}

function commitCurrentTurn() {
  pendingTurnTimer = null;
  if (submitted || speaking) return;
  const heard = candidateTranscript();
  if (!heard) return;
  const routed = routeTranscript(heard, sessionActive);
  sessionActive = routed.active;
  resetTranscriptBuffers();

  if (routed.action === 'standby' || routed.action === 'deactivate') {
    setVoiceState('standby');
    setHint('In standby. Dica “Jarvis”.');
    return;
  }
  if (routed.action === 'activate') {
    setVoiceState('listening');
    setHint('La ascolto, signore.');
    void speakClonedVoice(ACTIVATION_PHRASE, { short: true });
    return;
  }
  if (routed.action !== 'submit' || !routed.command) return;

  submitted = true;
  stopRecognition();
  setHint('');
  emitVoiceInput(routed.command);
}

function scheduleTurnCommit() {
  clearPendingTurn();
  pendingTurnTimer = window.setTimeout(commitCurrentTurn, TURN_SILENCE_MS);
}

function startRecognition() {
  if (!RecognitionCtor || !voiceRuntimeStarted || recognitionRunning || speaking) return;
  submitted = false;
  resetTranscriptBuffers();
  recognition = new RecognitionCtor();
  recognition.lang = 'it-IT';
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognitionRunning = true;
    setVoiceState(sessionActive ? 'listening' : 'standby');
    setHint(sessionActive ? 'La ascolto, signore.' : 'In standby. Dica “Jarvis”.');
  };

  recognition.onspeechstart = () => {
    if (sessionActive) {
      setVoiceState('listening');
      setHint('La ascolto, signore.');
    }
  };

  recognition.onresult = (event) => {
    let newestInterim = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const text = String(result?.[0]?.transcript || '').trim();
      if (!text) continue;
      if (result.isFinal) finalBuffer = `${finalBuffer} ${text}`.replace(/\s+/g, ' ').trim();
      else newestInterim = text;
    }
    interimBuffer = newestInterim;
    const heard = candidateTranscript();
    if (!heard || submitted) return;
    const routed = routeTranscript(heard, sessionActive);
    if (routed.action === 'activate' || routed.action === 'submit') {
      setVoiceState('listening', heard);
      setHint(routed.command ? `Ho sentito: ${routed.command}` : 'La ascolto, signore.');
    }
    scheduleTurnCommit();
  };

  recognition.onerror = (event) => {
    recognitionRunning = false;
    if (event.error === 'aborted') return;
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      voiceRuntimeStarted = false;
      setVoiceState('blocked', event.error);
      setHint('Il microfono è bloccato per questo sito. Consenta il microfono una sola volta.');
      installOneTimeGesture(startVoiceRuntime);
      return;
    }
    if (event.error !== 'no-speech') {
      console.warn('[JARVIS] Speech recognition:', event.error);
      setVoiceState('recognition-error', event.error);
    }
  };

  recognition.onend = () => {
    recognitionRunning = false;
    recognition = null;
    clearPendingTurn();
    if (!submitted && !speaking && candidateTranscript()) {
      commitCurrentTurn();
      return;
    }
    scheduleRecognitionRestart();
  };

  try {
    recognition.start();
  } catch (error) {
    recognitionRunning = false;
    recognition = null;
    console.warn('[JARVIS] Unable to start recognition:', error);
    scheduleRecognitionRestart(450);
  }
}

async function startVoiceRuntime({ requestPermission = true } = {}) {
  if (!RecognitionCtor) {
    setVoiceState('unsupported');
    setHint('Il riconoscimento vocale richiede Chrome o Edge aggiornato.');
    return;
  }
  let allowed = true;
  if (requestPermission || !micStream?.active) allowed = await ensureMicrophoneStream();
  if (!allowed) {
    setVoiceState('permission-needed');
    setHint('Autorizzi il microfono una sola volta; poi JARVIS partirà automaticamente.');
    installOneTimeGesture(startVoiceRuntime);
    return;
  }
  voiceRuntimeStarted = true;
  startMicMonitor();
  setVoiceState('standby');
  startRecognition();
}

async function bootstrapVoiceRuntime() {
  if (!RecognitionCtor) {
    setVoiceState('unsupported');
    return;
  }
  if (navigator.permissions?.query) {
    try {
      const status = await navigator.permissions.query({ name: 'microphone' });
      if (status.state === 'granted') {
        await startVoiceRuntime({ requestPermission: false });
        return;
      }
      if (status.state === 'denied') {
        setVoiceState('blocked');
        setHint('Il microfono è disattivato nelle autorizzazioni del sito.');
        return;
      }
    } catch {
      // Some browsers do not expose microphone through Permissions API.
    }
  }
  setVoiceState('permission-needed');
  setHint('Prima attivazione: tocchi una volta e consenta il microfono. Poi sarà automatico.');
  installOneTimeGesture(startVoiceRuntime);
}

window.addEventListener('jarvis:reply-ready', (event) => {
  if (!sessionActive) return;
  void speakClonedVoice(event?.detail?.text || '', { short: false });
});

// The web UI still emits a legacy automatic greeting event. Stable voice mode
// deliberately ignores it: the first spoken response happens only after the
// owner says "Jarvis" or "Hey Jarvis".
window.addEventListener('jarvis:greeting', () => {});

if (process.env.NODE_ENV !== 'test') {
  if (document.readyState === 'complete') window.setTimeout(bootstrapVoiceRuntime, 0);
  else window.addEventListener('load', bootstrapVoiceRuntime, { once: true });

  window.addEventListener('beforeunload', () => {
    voiceRuntimeStarted = false;
    stopRecognition();
    stopAudio();
    if (micMonitorFrame) window.cancelAnimationFrame(micMonitorFrame);
    micMonitorFrame = 0;
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    if (micMonitorContext && micMonitorContext.state !== 'closed') micMonitorContext.close().catch(() => {});
    if (pcmContext && pcmContext.state !== 'closed') pcmContext.close().catch(() => {});
  });
}
