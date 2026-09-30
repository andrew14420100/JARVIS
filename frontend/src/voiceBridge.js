// JARVIS browser voice bridge for the Emergent-hosted web runtime.
//
// The browser owns microphone capture. Modern browsers require microphone
// consent at least once for a site; after that permission is persisted, JARVIS
// can resume listening automatically on later visits without another prompt.

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
const pcmSources = new Set();

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const CONVERSATION_WINDOW_MS = 45000;
const RESTART_DELAY_MS = 280;

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

function stopRecognition() {
  if (!recognition) return;
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

async function requestMicrophone() {
  if (!navigator.mediaDevices?.getUserMedia) return false;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    stream.getTracks().forEach((track) => track.stop());
    return true;
  } catch (error) {
    console.warn('[JARVIS] Microphone permission:', error);
    return false;
  }
}

function scheduleRecognitionRestart(delay = RESTART_DELAY_MS) {
  if (!voiceRuntimeStarted || speaking || recognitionRunning) return;
  window.setTimeout(() => {
    if (voiceRuntimeStarted && !speaking && !recognitionRunning) startRecognition();
  }, delay);
}

function startRecognition() {
  if (!RecognitionCtor || !voiceRuntimeStarted || recognitionRunning || speaking) return;

  submitted = false;
  recognition = new RecognitionCtor();
  recognition.lang = 'it-IT';
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognitionRunning = true;
    const activeConversation = Date.now() < conversationDeadline;
    setVoiceState(activeConversation ? 'listening' : 'standby');
    setHint(activeConversation ? 'La ascolto, signore.' : 'In standby. Dica “Jarvis”.');
  };

  recognition.onresult = (event) => {
    let finalText = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result?.isFinal) finalText += result?.[0]?.transcript || '';
    }

    finalText = finalText.trim();
    if (!finalText || submitted) return;

    const activeConversation = Date.now() < conversationDeadline;
    const parsed = normalizeWakeTranscript(finalText);

    if (!activeConversation) {
      if (!parsed.activated) {
        // Ignore room conversation until JARVIS is explicitly invoked.
        return;
      }

      conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
      if (!parsed.command) {
        setVoiceState('listening');
        setHint('La ascolto, signore.');
        return;
      }

      finalText = parsed.command;
    }

    submitted = true;
    stopRecognition();
    conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
    setHint('');
    emitVoiceInput(finalText);
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
    scheduleRecognitionRestart();
  };

  try {
    recognition.start();
  } catch (error) {
    recognitionRunning = false;
    recognition = null;
    console.warn('[JARVIS] Unable to start recognition:', error);
    scheduleRecognitionRestart(700);
  }
}

async function startVoiceRuntime({ requestPermission = true } = {}) {
  if (!RecognitionCtor) {
    setVoiceState('unsupported');
    setHint('Il riconoscimento vocale richiede Chrome o Edge aggiornato.');
    return;
  }

  let allowed = true;
  if (requestPermission) allowed = await requestMicrophone();
  if (!allowed) {
    setVoiceState('permission-needed');
    setHint('Autorizzi il microfono una sola volta; poi JARVIS partirà automaticamente.');
    installOneTimeGesture(startVoiceRuntime);
    return;
  }

  voiceRuntimeStarted = true;
  setVoiceState('standby');
  startRecognition();
}

async function bootstrapVoiceRuntime() {
  if (!RecognitionCtor) {
    setVoiceState('unsupported');
    return;
  }

  // If the browser already remembers microphone permission, start hands-free
  // immediately without asking the user to touch the page again.
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

  // First use only: browsers require a user gesture before showing the prompt.
  setVoiceState('permission-needed');
  setHint('Prima attivazione: tocchi una volta e consenta il microfono. Poi sarà automatico.');
  installOneTimeGesture(startVoiceRuntime);
}

function reopenConversation() {
  conversationDeadline = Date.now() + CONVERSATION_WINDOW_MS;
  speaking = false;
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

  let scheduledAt = ctx.currentTime + 0.035;
  let carry = new Uint8Array(0);
  let heardAnything = false;
  speaking = true;
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

    const startAt = Math.max(scheduledAt, ctx.currentTime + 0.015);
    source.start(startAt);
    scheduledAt = startAt + buffer.duration;
    heardAnything = true;
  }

  if (!heardAnything) {
    reopenConversation();
    return;
  }

  const remainingMs = Math.max(0, (scheduledAt - ctx.currentTime) * 1000) + 60;
  window.setTimeout(reopenConversation, remainingMs);
}

async function playGeneratedAudio(blob) {
  stopAudio();
  activeAudioUrl = URL.createObjectURL(blob);
  activeAudio = new Audio(activeAudioUrl);
  activeAudio.preload = 'auto';
  activeAudio.onplaying = () => {
    speaking = true;
    setVoiceState('speaking');
  };
  activeAudio.onended = reopenConversation;
  activeAudio.onerror = reopenConversation;
  await activeAudio.play();
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
      throw new Error(await fetchErrorDetail(response, 'Voce non disponibile.'));
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
    console.warn('[JARVIS] TTS:', error);
    // Voice output and microphone input are independent. Even if CosyVoice is
    // not ready yet, immediately return to listening so spoken commands still work.
    speaking = false;
    reopenConversation();
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

bootstrapVoiceRuntime();

window.addEventListener('beforeunload', () => {
  voiceRuntimeStarted = false;
  stopRecognition();
  stopAudio();
  if (pcmContext && pcmContext.state !== 'closed') {
    pcmContext.close().catch(() => {});
  }
});
