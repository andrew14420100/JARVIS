// JARVIS browser voice bridge for the Emergent-hosted web runtime.
//
// Goal: make speech feel like a live conversation rather than push-to-talk.
// The browser keeps a continuous recognition session, uses interim transcripts,
// commits the turn after a short natural pause, and supports barge-in while
// JARVIS is speaking. Microphone permission is still controlled by the browser.

let recognition = null;
let recognitionRunning = false;
let speaking = false;
let submitted = false;
let greetingSpoken = false;
let voiceRuntimeStarted = false;
let conversationDeadline = 0;
let retryInstalled = false;
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
const pcmSources = new Set();

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const CONVERSATION_WINDOW_MS = 60000;
const RESTART_DELAY_MS = 160;
const TURN_SILENCE_MS = 700;
const BARGE_IN_RMS = 0.055;
const BARGE_IN_HOLD_MS = 220;
const BARGE_IN_GUARD_MS = 650;

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

function normalizeWakeTranscript(text) {
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

function clearPendingTurn() {
  if (pendingTurnTimer) window.clearTimeout(pendingTurnTimer);
  pendingTurnTimer = null;
}

function resetTranscriptBuffers() {
  finalBuffer = '';
  interimBuffer = '';
  clearPendingTurn();
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
    // Recognition may already be closing.
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
      // Ignore already-completed requests.
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
      // Ignore cleanup races.
    }
  }
  activeAudio = null;
  if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
  activeAudioUrl = '';

  if ('speechSynthesis' in window) {
    try {
      window.speechSynthesis.cancel();
    } catch {
      // Ignore browser speech cleanup errors.
    }
  }
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
      for (let index = 0; index < samples.length; index += 1) {
        sum += samples[index] * samples[index];
      }
      const rms = Math.sqrt(sum / samples.length);
      if (
        speaking
        && Date.now() - speechStartedAt > BARGE_IN_GUARD_MS
        && Date.now() < conversationDeadline
        && rms >= BARGE_IN_RMS
      ) {
        if (!bargeInSince) bargeInSince = performance.now();
        if (performance.now() - bargeInSince >= BARGE_IN_HOLD_MS) {
          bargeInSince = 0;
          interruptForUserSpeech();
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

function interruptForUserSpeech() {
  if (!speaking) return;
  speaking = false;
  stopAudio();
  conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
  setVoiceState('listening');
  setHint('La ascolto, signore.');
  resetTranscriptBuffers();
  startRecognition();
}

function scheduleRecognitionRestart(delay = RESTART_DELAY_MS) {
  if (!voiceRuntimeStarted || recognitionRunning) return;
  window.setTimeout(() => {
    if (voiceRuntimeStarted && !recognitionRunning) startRecognition();
  }, delay);
}

function candidateTranscript() {
  return `${finalBuffer} ${interimBuffer}`.replace(/\s+/g, ' ').trim();
}

function commitCurrentTurn() {
  pendingTurnTimer = null;
  if (submitted || speaking) return;
  let text = candidateTranscript();
  if (!text) return;
  const activeConversation = Date.now() < conversationDeadline;
  const parsed = normalizeWakeTranscript(text);

  if (!activeConversation) {
    if (!parsed.activated) {
      resetTranscriptBuffers();
      setVoiceState('standby');
      setHint('In standby. Dica “Jarvis”.');
      return;
    }
    conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
    if (!parsed.command) {
      resetTranscriptBuffers();
      setVoiceState('listening');
      setHint('La ascolto, signore.');
      return;
    }
    text = parsed.command;
  }

  text = text.trim();
  if (!text) return;
  submitted = true;
  conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
  resetTranscriptBuffers();
  stopRecognition();
  setHint('');
  emitVoiceInput(text);
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
    const activeConversation = Date.now() < conversationDeadline;
    setVoiceState(activeConversation ? 'listening' : 'standby');
    setHint(activeConversation ? 'La ascolto, signore.' : 'In standby. Dica “Jarvis”.');
  };

  recognition.onspeechstart = () => {
    if (Date.now() < conversationDeadline) {
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
      if (result.isFinal) {
        finalBuffer = `${finalBuffer} ${text}`.replace(/\s+/g, ' ').trim();
      } else {
        newestInterim = text;
      }
    }

    interimBuffer = newestInterim;
    const heard = candidateTranscript();
    if (!heard || submitted) return;
    const activeConversation = Date.now() < conversationDeadline;
    const parsed = normalizeWakeTranscript(heard);

    if (!activeConversation && parsed.activated) {
      conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
      setVoiceState('listening', heard);
      setHint(parsed.command ? `Ho sentito: ${parsed.command}` : 'La ascolto, signore.');
    } else if (activeConversation) {
      setVoiceState('listening', heard);
      setHint(`Ho sentito: ${heard}`);
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

function reopenConversation() {
  conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
  speaking = false;
  resetTranscriptBuffers();
  if (!recognitionRunning) startRecognition();
}

async function getPcmContext() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) throw new Error('Web Audio non supportato dal browser.');
  if (!pcmContext || pcmContext.state === 'closed') pcmContext = new AudioContextCtor();
  if (pcmContext.state === 'suspended') await pcmContext.resume();
  return pcmContext;
}

function pcm16ToFloat32(bytes) {
  const sampleCount = Math.floor(bytes.byteLength / 2);
  const floats = new Float32Array(sampleCount);
  const view = new DataView(bytes.buffer, bytes.byteOffset, sampleCount * 2);
  for (let i = 0; i < sampleCount; i += 1) {
    const value = view.getInt16(i * 2, true);
    floats[i] = value < 0 ? value / 32768 : value / 32767;
  }
  return floats;
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
    let bytes;
    if (carry.byteLength) {
      bytes = new Uint8Array(carry.byteLength + value.byteLength);
      bytes.set(carry, 0);
      bytes.set(value, carry.byteLength);
    } else {
      bytes = value;
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

function selectBrowserVoice() {
  if (!('speechSynthesis' in window)) return null;
  const voices = window.speechSynthesis.getVoices();
  const italian = voices.filter((voice) => String(voice.lang || '').toLowerCase().startsWith('it'));
  const preferred = italian.find((voice) => /giuseppe|diego|cosimo|male|neural/i.test(voice.name));
  return preferred || italian[0] || voices[0] || null;
}

async function speakBrowserFallback(text) {
  if (!('speechSynthesis' in window) || !window.SpeechSynthesisUtterance) {
    reopenConversation();
    return;
  }
  stopAudio();
  await new Promise((resolve) => {
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = selectBrowserVoice();
    if (voice) utterance.voice = voice;
    utterance.lang = voice?.lang || 'it-IT';
    utterance.rate = 1.02;
    utterance.pitch = 0.92;
    utterance.volume = 1;
    utterance.onstart = () => {
      speaking = true;
      speechStartedAt = Date.now();
      setVoiceState('speaking');
      setHint('');
    };
    utterance.onend = () => {
      resolve();
      reopenConversation();
    };
    utterance.onerror = () => {
      resolve();
      reopenConversation();
    };
    window.speechSynthesis.speak(utterance);
  });
}

async function fetchErrorDetail(response, fallback) {
  try {
    const payload = await response.json();
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function speak(text, { greeting = false } = {}) {
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
    const endpoint = greeting ? '/api/tts' : '/api/tts/stream';
    pcmAbortController = new AbortController();
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: content }),
      signal: pcmAbortController.signal,
    });
    if (!response.ok) {
      throw new Error(await fetchErrorDetail(response, 'Voce clonata non disponibile.'));
    }
    if (!greeting && response.headers.get('X-Audio-Format') === 'pcm_s16le_mono') {
      await playPcmStream(response);
      return;
    }
    const blob = await response.blob();
    if (!blob.size) throw new Error('Audio vuoto.');
    await playGeneratedAudio(blob);
  } catch (error) {
    if (error?.name === 'AbortError') return;
    console.warn('[JARVIS] TTS primario:', error);
    setHint('Voce clonata in preparazione: uso temporaneamente la voce del browser.');
    speaking = false;
    await speakBrowserFallback(content);
  }
}

window.addEventListener('jarvis:greeting', (event) => {
  if (greetingSpoken) return;
  greetingSpoken = true;
  speak(event?.detail?.text || '', { greeting: true });
});

window.addEventListener('jarvis:reply-ready', (event) => {
  speak(event?.detail?.text || '', { greeting: false });
});

if (document.readyState === 'complete') {
  window.setTimeout(bootstrapVoiceRuntime, 0);
} else {
  window.addEventListener('load', bootstrapVoiceRuntime, { once: true });
}

window.addEventListener('beforeunload', () => {
  voiceRuntimeStarted = false;
  stopRecognition();
  stopAudio();
  if (micMonitorFrame) window.cancelAnimationFrame(micMonitorFrame);
  micMonitorFrame = 0;
  if (micStream) micStream.getTracks().forEach((track) => track.stop());
  micStream = null;
  if (micMonitorContext && micMonitorContext.state !== 'closed') {
    micMonitorContext.close().catch(() => {});
  }
  if (pcmContext && pcmContext.state !== 'closed') {
    pcmContext.close().catch(() => {});
  }
});
