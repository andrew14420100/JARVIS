// Human realtime voice bridge for JARVIS.
// Uses the browser path that proved smoother on the target PC: persistent
// microphone permission, browser speech recognition, browser echo processing
// and WebAudio PCM scheduling. The UI stays voice-only: no mic button or text box.

let recognition = null;
let recognitionRunning = false;
let runtimeStarted = false;
let speaking = false;
let submitted = false;
let pendingTurnTimer = null;
let finalBuffer = '';
let interimBuffer = '';
let micStream = null;
let micContext = null;
let micAnalyser = null;
let micFrame = 0;
let bargeSince = 0;
let speechStartedAt = 0;
let pcmContext = null;
let pcmAbortController = null;
let pcmGeneration = 0;
const pcmSources = new Set();

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const TURN_SILENCE_MS = 360;
const RESTART_DELAY_MS = 120;
const BARGE_IN_RMS = 0.050;
const BARGE_IN_HOLD_MS = 180;
const BARGE_IN_GUARD_MS = 420;

function setHint(text) {
  const hint = document.querySelector('.hint');
  if (hint) hint.textContent = text || '';
}

function setVoiceState(state, detail = '') {
  window.dispatchEvent(new CustomEvent('jarvis:voice-state', { detail: { state, detail } }));
}

function emitVoiceInput(text) {
  const value = String(text || '').trim();
  if (!value) return;
  setVoiceState('submitted', value);
  window.dispatchEvent(new CustomEvent('jarvis:voice-input', { detail: { text: value } }));
}

function clearTurnTimer() {
  if (pendingTurnTimer) window.clearTimeout(pendingTurnTimer);
  pendingTurnTimer = null;
}

function resetBuffers() {
  finalBuffer = '';
  interimBuffer = '';
  clearTurnTimer();
}

function currentTranscript() {
  return `${finalBuffer} ${interimBuffer}`.replace(/\s+/g, ' ').trim();
}

function stopRecognition() {
  clearTurnTimer();
  if (!recognition) {
    recognitionRunning = false;
    return;
  }
  try { recognition.abort(); } catch {}
  recognition = null;
  recognitionRunning = false;
}

function stopAudio() {
  pcmGeneration += 1;
  if (pcmAbortController) {
    try { pcmAbortController.abort(); } catch {}
  }
  pcmAbortController = null;
  for (const source of pcmSources) {
    try { source.stop(); } catch {}
  }
  pcmSources.clear();
}

async function ensureMicrophone() {
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
    console.warn('[JARVIS] Browser microphone:', error);
    return false;
  }
}

function startMicMonitor() {
  if (!micStream?.active || micFrame) return;
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) return;
  try {
    micContext = micContext || new AudioContextCtor();
    const source = micContext.createMediaStreamSource(micStream);
    micAnalyser = micContext.createAnalyser();
    micAnalyser.fftSize = 1024;
    source.connect(micAnalyser);
    const samples = new Float32Array(micAnalyser.fftSize);

    const tick = () => {
      if (!runtimeStarted || !micAnalyser) {
        micFrame = 0;
        return;
      }
      micAnalyser.getFloatTimeDomainData(samples);
      let sum = 0;
      for (let i = 0; i < samples.length; i += 1) sum += samples[i] * samples[i];
      const rms = Math.sqrt(sum / samples.length);

      // Natural interruption: keep the browser microphone stream alive while
      // JARVIS speaks. If the owner starts talking, stop playback and restart
      // speech recognition immediately.
      if (speaking && Date.now() - speechStartedAt > BARGE_IN_GUARD_MS && rms >= BARGE_IN_RMS) {
        if (!bargeSince) bargeSince = performance.now();
        if (performance.now() - bargeSince >= BARGE_IN_HOLD_MS) {
          bargeSince = 0;
          speaking = false;
          stopAudio();
          resetBuffers();
          setVoiceState('listening');
          startRecognition();
        }
      } else {
        bargeSince = 0;
      }
      micFrame = window.requestAnimationFrame(tick);
    };
    micFrame = window.requestAnimationFrame(tick);
  } catch (error) {
    console.warn('[JARVIS] Browser mic monitor:', error);
    micFrame = 0;
  }
}

function scheduleRestart(delay = RESTART_DELAY_MS) {
  if (!runtimeStarted || recognitionRunning || speaking) return;
  window.setTimeout(() => {
    if (runtimeStarted && !recognitionRunning && !speaking) startRecognition();
  }, delay);
}

function reopenConversation() {
  speaking = false;
  submitted = false;
  resetBuffers();
  setVoiceState('listening');
  setHint('');
  scheduleRestart(40);
}

function commitTurn() {
  pendingTurnTimer = null;
  if (submitted || speaking) return;
  const heard = currentTranscript();
  if (!heard) return;
  submitted = true;
  resetBuffers();
  stopRecognition();
  setHint('');
  emitVoiceInput(heard);
}

function scheduleTurnCommit() {
  clearTurnTimer();
  pendingTurnTimer = window.setTimeout(commitTurn, TURN_SILENCE_MS);
}

function startRecognition() {
  if (!RecognitionCtor || !runtimeStarted || recognitionRunning || speaking) return;
  submitted = false;
  resetBuffers();
  recognition = new RecognitionCtor();
  recognition.lang = 'it-IT';
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognitionRunning = true;
    setVoiceState('listening');
    setHint('');
  };

  recognition.onresult = (event) => {
    let newestInterim = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) {
      const result = event.results[i];
      const text = String(result?.[0]?.transcript || '').trim();
      if (!text) continue;
      if (result.isFinal) finalBuffer = `${finalBuffer} ${text}`.replace(/\s+/g, ' ').trim();
      else newestInterim = text;
    }
    interimBuffer = newestInterim;
    if (!currentTranscript() || submitted) return;
    setVoiceState('listening');
    scheduleTurnCommit();
  };

  recognition.onerror = (event) => {
    recognitionRunning = false;
    if (event.error === 'aborted' || event.error === 'no-speech') return;
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      runtimeStarted = false;
      setVoiceState('blocked', event.error);
      setHint('Consenta il microfono a localhost una sola volta.');
      return;
    }
    console.warn('[JARVIS] SpeechRecognition:', event.error);
    setVoiceState('recognition-error', event.error);
  };

  recognition.onend = () => {
    recognitionRunning = false;
    recognition = null;
    if (!submitted && !speaking && currentTranscript()) {
      commitTurn();
      return;
    }
    scheduleRestart();
  };

  try {
    recognition.start();
  } catch (error) {
    recognitionRunning = false;
    recognition = null;
    console.warn('[JARVIS] SpeechRecognition start:', error);
    scheduleRestart(350);
  }
}

function pcm16ToFloat32(bytes) {
  const count = Math.floor(bytes.byteLength / 2);
  const out = new Float32Array(count);
  const view = new DataView(bytes.buffer, bytes.byteOffset, count * 2);
  for (let i = 0; i < count; i += 1) {
    const value = view.getInt16(i * 2, true);
    out[i] = value < 0 ? value / 32768 : value / 32767;
  }
  return out;
}

async function getPcmContext() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) throw new Error('WebAudio non disponibile.');
  if (!pcmContext || pcmContext.state === 'closed') pcmContext = new AudioContextCtor();
  if (pcmContext.state === 'suspended') await pcmContext.resume();
  return pcmContext;
}

async function playPcmStream(response) {
  const generation = pcmGeneration;
  const ctx = await getPcmContext();
  const sampleRate = Number(response.headers.get('X-Sample-Rate')) || 24000;
  const reader = response.body?.getReader?.();
  if (!reader) throw new Error('Streaming PCM non disponibile.');

  let scheduledAt = ctx.currentTime + 0.020;
  let carry = new Uint8Array(0);
  let heard = false;
  speaking = true;
  speechStartedAt = Date.now();
  setVoiceState('speaking');

  while (true) {
    const { value, done } = await reader.read();
    if (done || generation !== pcmGeneration) break;
    if (!value?.byteLength) continue;
    let bytes = value;
    if (carry.byteLength) {
      const merged = new Uint8Array(carry.byteLength + value.byteLength);
      merged.set(carry, 0);
      merged.set(value, carry.byteLength);
      bytes = merged;
    }
    const usable = bytes.byteLength - (bytes.byteLength % 2);
    carry = usable < bytes.byteLength ? bytes.slice(usable) : new Uint8Array(0);
    if (!usable) continue;

    const floats = pcm16ToFloat32(bytes.subarray(0, usable));
    if (!floats.length) continue;
    const buffer = ctx.createBuffer(1, floats.length, sampleRate);
    buffer.copyToChannel(floats, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    pcmSources.add(source);
    source.onended = () => pcmSources.delete(source);
    const startAt = Math.max(scheduledAt, ctx.currentTime + 0.008);
    source.start(startAt);
    scheduledAt = startAt + buffer.duration;
    heard = true;
  }

  if (!heard || generation !== pcmGeneration) {
    if (generation === pcmGeneration) reopenConversation();
    return;
  }
  const remainingMs = Math.max(0, (scheduledAt - ctx.currentTime) * 1000) + 25;
  window.setTimeout(() => {
    if (generation === pcmGeneration) reopenConversation();
  }, remainingMs);
}

async function speakClonedVoice(text) {
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
    pcmAbortController = new AbortController();
    const response = await fetch(`${API_BASE}/api/tts/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: content }),
      signal: pcmAbortController.signal,
    });
    if (!response.ok) throw new Error('CosyVoice non disponibile.');
    await playPcmStream(response);
  } catch (error) {
    if (error?.name !== 'AbortError') {
      console.warn('[JARVIS] CosyVoice browser:', error);
      setVoiceState('voice-error', error?.message || 'CosyVoice non disponibile');
    }
    reopenConversation();
  }
}

async function startHumanVoice() {
  if (!RecognitionCtor) {
    setVoiceState('unsupported');
    setHint('Per la modalità voce fluida usa Chrome o Edge aggiornato.');
    return;
  }
  const allowed = await ensureMicrophone();
  if (!allowed) {
    setVoiceState('permission-needed');
    setHint('Consenta il microfono a localhost una sola volta.');
    return;
  }
  runtimeStarted = true;
  startMicMonitor();
  setVoiceState('listening');
  startRecognition();
}

window.addEventListener('jarvis:reply-ready', (event) => {
  void speakClonedVoice(event?.detail?.text || '');
});

// The page should not consume a model turn merely to greet. JARVIS is already
// present and listens immediately; the first natural reply follows the user.
window.addEventListener('jarvis:greeting', () => {});

if (process.env.NODE_ENV !== 'test') {
  const boot = () => { void startHumanVoice(); };
  if (document.readyState === 'complete') window.setTimeout(boot, 0);
  else window.addEventListener('load', boot, { once: true });

  window.addEventListener('beforeunload', () => {
    runtimeStarted = false;
    stopRecognition();
    stopAudio();
    if (micFrame) window.cancelAnimationFrame(micFrame);
    micFrame = 0;
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    if (micContext && micContext.state !== 'closed') micContext.close().catch(() => {});
    if (pcmContext && pcmContext.state !== 'closed') pcmContext.close().catch(() => {});
  });
}
