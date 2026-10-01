// Human realtime voice bridge for JARVIS Realtime Core v2.
// One browser-owned microphone, browser echo processing and one native
// CosyVoice bistream session per answer. No mic button and no text box.

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
let audioAbortController = null;
let audioGeneration = 0;
let scheduledAt = 0;
const pcmSources = new Set();

let replyGeneration = 0;
let ttsSessionId = '';
let ttsSessionPromise = null;
let ttsPushChain = Promise.resolve();
let ttsTextBuffer = '';
let ttsFirstPacket = true;
let replyText = '';
let bistreamFailed = false;

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const TURN_SILENCE_MS = 320;
const RESTART_DELAY_MS = 90;
const BARGE_IN_RMS = 0.050;
const BARGE_IN_HOLD_MS = 170;
const BARGE_IN_GUARD_MS = 380;

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

function stopScheduledAudio() {
  audioGeneration += 1;
  if (audioAbortController) {
    try { audioAbortController.abort(); } catch {}
  }
  audioAbortController = null;
  for (const source of pcmSources) {
    try { source.stop(); } catch {}
  }
  pcmSources.clear();
  scheduledAt = 0;
  speaking = false;
}

async function finishRemoteSession(sessionId) {
  if (!sessionId) return;
  try {
    await fetch(`${API_BASE}/api/realtime/tts/bistream/${encodeURIComponent(sessionId)}/finish`, {
      method: 'POST',
      cache: 'no-store',
    });
  } catch {
    // Session may already have been closed by the service.
  }
}

function cancelCurrentReply({ notify = false } = {}) {
  replyGeneration += 1;
  const oldSession = ttsSessionId;
  ttsSessionId = '';
  ttsSessionPromise = null;
  ttsPushChain = Promise.resolve();
  ttsTextBuffer = '';
  ttsFirstPacket = true;
  replyText = '';
  bistreamFailed = false;
  stopScheduledAudio();
  if (oldSession) void finishRemoteSession(oldSession);
  if (notify) window.dispatchEvent(new CustomEvent('jarvis:barge-in'));
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

      if (speaking && Date.now() - speechStartedAt > BARGE_IN_GUARD_MS && rms >= BARGE_IN_RMS) {
        if (!bargeSince) bargeSince = performance.now();
        if (performance.now() - bargeSince >= BARGE_IN_HOLD_MS) {
          bargeSince = 0;
          cancelCurrentReply({ notify: true });
          resetBuffers();
          setVoiceState('listening');
          setHint('');
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
  scheduleRestart(25);
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
    scheduleRestart(300);
  }
}

export function splitSpeechBuffer(buffer, { firstPacket = false, final = false } = {}) {
  let rest = String(buffer || '');
  const segments = [];
  let first = Boolean(firstPacket);

  while (rest) {
    const target = first ? 26 : 52;
    const maxLen = first ? 46 : 92;
    let boundary = null;
    const punctuation = [...rest.matchAll(/[.!?;:,](?=\s|$)/g)];
    for (const match of punctuation) {
      const end = (match.index || 0) + 1;
      if (end >= target) {
        boundary = end;
        break;
      }
    }
    if (boundary == null && rest.length >= maxLen) {
      const cut = rest.lastIndexOf(' ', maxLen);
      if (cut >= Math.max(18, Math.floor(target / 2))) boundary = cut;
    }
    if (boundary == null) break;
    const piece = rest.slice(0, boundary).trim();
    rest = rest.slice(boundary).trimStart();
    if (piece) {
      segments.push(piece);
      first = false;
    }
  }

  if (final && rest.trim()) {
    segments.push(rest.trim());
    rest = '';
  }
  return { segments, rest, firstPacket: first };
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

async function playBistreamAudio(response, generation) {
  const ctx = await getPcmContext();
  const sampleRate = Number(response.headers.get('X-Sample-Rate')) || 24000;
  const reader = response.body?.getReader?.();
  if (!reader) throw new Error('Streaming PCM non disponibile.');
  let carry = new Uint8Array(0);
  let heard = false;
  scheduledAt = Math.max(scheduledAt, ctx.currentTime + 0.018);

  while (true) {
    const { value, done } = await reader.read();
    if (done || generation !== audioGeneration) break;
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
    if (!heard) {
      heard = true;
      speaking = true;
      speechStartedAt = Date.now();
      setVoiceState('speaking');
    }
    const buffer = ctx.createBuffer(1, floats.length, sampleRate);
    buffer.copyToChannel(floats, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    pcmSources.add(source);
    source.onended = () => pcmSources.delete(source);
    const startAt = Math.max(scheduledAt, ctx.currentTime + 0.006);
    source.start(startAt);
    scheduledAt = startAt + buffer.duration;
  }

  if (generation !== audioGeneration) return;
  if (!heard) {
    reopenConversation();
    return;
  }
  const remainingMs = Math.max(0, (scheduledAt - ctx.currentTime) * 1000) + 20;
  window.setTimeout(() => {
    if (generation === audioGeneration) reopenConversation();
  }, remainingMs);
}

async function startBistreamSession(generation) {
  if (ttsSessionPromise) return ttsSessionPromise;
  ttsSessionPromise = (async () => {
    const response = await fetch(`${API_BASE}/api/realtime/tts/bistream/start`, {
      method: 'POST',
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('CosyVoice bistream non disponibile.');
    const data = await response.json();
    if (generation !== replyGeneration) throw new DOMException('Turn replaced', 'AbortError');
    ttsSessionId = String(data.session_id || '');
    if (!ttsSessionId) throw new Error('Sessione CosyVoice non valida.');

    audioAbortController = new AbortController();
    const localAudioGeneration = audioGeneration;
    const audioResponse = await fetch(
      `${API_BASE}/api/realtime/tts/bistream/${encodeURIComponent(ttsSessionId)}/audio`,
      { signal: audioAbortController.signal, cache: 'no-store' },
    );
    if (!audioResponse.ok) throw new Error('Audio CosyVoice bistream non disponibile.');
    void playBistreamAudio(audioResponse, localAudioGeneration).catch((error) => {
      if (error?.name !== 'AbortError') console.warn('[JARVIS] Bistream audio:', error);
    });
    return ttsSessionId;
  })().catch((error) => {
    bistreamFailed = true;
    console.warn('[JARVIS] CosyVoice bistream start:', error);
    return '';
  });
  return ttsSessionPromise;
}

function queueSpeechSegment(text, generation) {
  const packet = String(text || '').trim();
  if (!packet || generation !== replyGeneration) return;
  ttsPushChain = ttsPushChain.catch(() => {}).then(async () => {
    if (generation !== replyGeneration || bistreamFailed) return;
    const sessionId = await startBistreamSession(generation);
    if (!sessionId || generation !== replyGeneration) return;
    const response = await fetch(
      `${API_BASE}/api/realtime/tts/bistream/${encodeURIComponent(sessionId)}/push`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: packet }),
        cache: 'no-store',
      },
    );
    if (!response.ok) throw new Error('Push CosyVoice fallito.');
  }).catch((error) => {
    bistreamFailed = true;
    console.warn('[JARVIS] CosyVoice bistream push:', error);
  });
}

function drainSpeechBuffer(final = false) {
  const result = splitSpeechBuffer(ttsTextBuffer, { firstPacket: ttsFirstPacket, final });
  ttsTextBuffer = result.rest;
  ttsFirstPacket = result.firstPacket;
  const generation = replyGeneration;
  for (const segment of result.segments) queueSpeechSegment(segment, generation);
}

async function fallbackWholeReply(text, generation) {
  if (generation !== replyGeneration || !text.trim()) return;
  try {
    audioAbortController = new AbortController();
    const response = await fetch(`${API_BASE}/api/tts/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text }),
      signal: audioAbortController.signal,
      cache: 'no-store',
    });
    if (!response.ok) throw new Error('CosyVoice non disponibile.');
    await playBistreamAudio(response, audioGeneration);
  } catch (error) {
    if (error?.name !== 'AbortError') {
      setVoiceState('voice-error', error?.message || 'CosyVoice non disponibile');
      reopenConversation();
    }
  }
}

function beginReplyTurn() {
  cancelCurrentReply();
  replyGeneration += 1;
  ttsTextBuffer = '';
  ttsFirstPacket = true;
  replyText = '';
  bistreamFailed = false;
  ttsPushChain = Promise.resolve();
}

function onReplyDelta(text) {
  const delta = String(text || '');
  if (!delta) return;
  replyText += delta;
  ttsTextBuffer += delta;
  drainSpeechBuffer(false);
}

async function onReplyDone() {
  const generation = replyGeneration;
  drainSpeechBuffer(true);
  await ttsPushChain.catch(() => {});
  if (generation !== replyGeneration) return;

  if (bistreamFailed || !ttsSessionId) {
    await fallbackWholeReply(replyText, generation);
    return;
  }
  const session = ttsSessionId;
  await finishRemoteSession(session);
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

window.addEventListener('jarvis:reply-start', beginReplyTurn);
window.addEventListener('jarvis:reply-delta', (event) => onReplyDelta(event?.detail?.text || ''));
window.addEventListener('jarvis:reply-done', () => { void onReplyDone(); });
window.addEventListener('jarvis:reply-error', () => {
  cancelCurrentReply();
  reopenConversation();
});

if (process.env.NODE_ENV !== 'test') {
  const boot = () => { void startHumanVoice(); };
  if (document.readyState === 'complete') window.setTimeout(boot, 0);
  else window.addEventListener('load', boot, { once: true });

  window.addEventListener('beforeunload', () => {
    runtimeStarted = false;
    stopRecognition();
    cancelCurrentReply();
    if (micFrame) window.cancelAnimationFrame(micFrame);
    micFrame = 0;
    if (micStream) micStream.getTracks().forEach((track) => track.stop());
    micStream = null;
    if (micContext && micContext.state !== 'closed') micContext.close().catch(() => {});
    if (pcmContext && pcmContext.state !== 'closed') pcmContext.close().catch(() => {});
  });
}
