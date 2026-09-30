let recognition = null;
let recognitionRunning = false;
let followupDeadline = 0;
let submitted = false;
let speaking = false;
let greetingSpoken = false;
let retryOnGestureInstalled = false;
let voiceSessionStarted = false;
let micPermissionGranted = false;
let activeAudio = null;
let activeAudioUrl = '';
let pcmContext = null;
let pcmAbortController = null;
let pcmGeneration = 0;
const pcmSources = new Set();

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const FOLLOWUP_MS = 20000;
const RESTART_DELAY_MS = 350;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');

function setHint(text) {
  const hint = document.querySelector('.hint');
  if (hint) hint.textContent = text || '';
}

function setVoiceState(state, detail = '') {
  window.dispatchEvent(new CustomEvent('jarvis:voice-state', {
    detail: { state, detail },
  }));
}

function stopRecognition() {
  if (!recognition) return;
  try {
    recognition.abort();
  } catch {
    // Ignore races while the browser is already closing recognition.
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
      // Ignore an already-finished request.
    }
  }
  pcmAbortController = null;

  for (const source of pcmSources) {
    try {
      source.stop();
    } catch {
      // Source may have already ended.
    }
  }
  pcmSources.clear();

  if (activeAudio) {
    try {
      activeAudio.pause();
      activeAudio.src = '';
    } catch {
      // Ignore media cleanup races.
    }
  }
  activeAudio = null;
  if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
  activeAudioUrl = '';
}

function emitVoiceInput(text) {
  const value = String(text || '').trim();
  if (!value) return;
  setVoiceState('submitted', value);
  window.dispatchEvent(new CustomEvent('jarvis:voice-input', { detail: { text: value } }));
}

function installGestureRetry(action) {
  if (retryOnGestureInstalled) return;
  retryOnGestureInstalled = true;
  const retry = () => {
    retryOnGestureInstalled = false;
    document.removeEventListener('pointerdown', retry, true);
    action();
  };
  document.addEventListener('pointerdown', retry, true);
}

async function ensureMicPermission() {
  if (micPermissionGranted) return true;
  if (!navigator.mediaDevices?.getUserMedia) {
    setVoiceState('unsupported', 'getUserMedia non disponibile');
    return false;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    stream.getTracks().forEach((track) => track.stop());
    micPermissionGranted = true;
    setVoiceState('ready');
    return true;
  } catch (error) {
    console.warn('[JARVIS] Microphone permission:', error);
    setVoiceState('blocked', error?.name || 'microphone-blocked');
    return false;
  }
}

function normalizeWakeTranscript(text) {
  const value = String(text || '').trim();
  if (!value) return { activated: false, command: '' };

  const wakePattern = /\b(?:hey\s+)?jarvis\b[\s,.:;!?-]*/i;
  const match = value.match(wakePattern);
  if (!match) return { activated: false, command: value };

  const index = match.index || 0;
  const command = `${value.slice(0, index)} ${value.slice(index + match[0].length)}`
    .replace(/\s+/g, ' ')
    .trim();
  return { activated: true, command };
}

function scheduleRecognitionRestart(delay = RESTART_DELAY_MS) {
  if (!voiceSessionStarted || speaking || recognitionRunning) return;
  window.setTimeout(() => {
    if (voiceSessionStarted && !speaking && !recognitionRunning) startRecognitionWindow();
  }, delay);
}

function startRecognitionWindow() {
  if (!RecognitionCtor || recognitionRunning || speaking || !voiceSessionStarted) return;

  submitted = false;
  recognition = new RecognitionCtor();
  recognition.lang = 'it-IT';
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognitionRunning = true;
    const inFollowup = Date.now() < followupDeadline;
    setVoiceState(inFollowup ? 'listening' : 'standby');
    setHint(inFollowup ? 'La ascolto, signore.' : 'Dica “Jarvis” per richiamare la mia attenzione.');
  };

  recognition.onresult = (event) => {
    let finalText = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result?.isFinal) finalText += result?.[0]?.transcript || '';
    }

    finalText = finalText.trim();
    if (!finalText || submitted) return;

    const inFollowup = Date.now() < followupDeadline;
    const parsed = normalizeWakeTranscript(finalText);

    if (!inFollowup && !parsed.activated) {
      // Room conversation while JARVIS is in standby is deliberately ignored.
      setVoiceState('standby');
      setHint('Dica “Jarvis” per richiamare la mia attenzione.');
      return;
    }

    if (!inFollowup && parsed.activated && !parsed.command) {
      followupDeadline = Date.now() + FOLLOWUP_MS;
      setVoiceState('listening');
      setHint('La ascolto, signore.');
      return;
    }

    const textToSubmit = inFollowup ? finalText : parsed.command;
    if (!textToSubmit) return;

    submitted = true;
    followupDeadline = 0;
    stopRecognition();
    setHint('');
    emitVoiceInput(textToSubmit);
  };

  recognition.onerror = (event) => {
    recognitionRunning = false;
    if (event.error === 'aborted') return;

    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      micPermissionGranted = false;
      setVoiceState('blocked', event.error);
      setHint('Microfono bloccato. Consenta il microfono al sito; se è nella preview Emergent, apra la preview in una nuova scheda.');
      installGestureRetry(startVoiceSession);
      return;
    }

    if (event.error === 'network') {
      setVoiceState('recognition-error', 'network');
      setHint('Il riconoscimento vocale del browser non è raggiungibile. Riprovo automaticamente.');
    } else if (event.error !== 'no-speech') {
      console.warn('[JARVIS] Speech recognition:', event.error);
      setVoiceState('recognition-error', event.error);
    }
  };

  recognition.onend = () => {
    recognitionRunning = false;
    recognition = null;
    if (!speaking && voiceSessionStarted) scheduleRecognitionRestart();
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

async function startVoiceSession() {
  if (!RecognitionCtor) {
    setVoiceState('unsupported');
    setHint('La conversazione vocale automatica richiede Chrome o Edge aggiornato.');
    return;
  }

  const allowed = await ensureMicPermission();
  if (!allowed) {
    setHint('Consenta l’accesso al microfono. Se Emergent è aperto in una preview incorporata, apra il sito in una nuova scheda.');
    installGestureRetry(startVoiceSession);
    return;
  }

  voiceSessionStarted = true;
  setVoiceState('standby');
  startRecognitionWindow();
}

async function openFollowupWindow(duration = FOLLOWUP_MS) {
  followupDeadline = Date.now() + duration;
  if (!voiceSessionStarted) {
    await startVoiceSession();
    return;
  }
  if (!speaking && !recognitionRunning) startRecognitionWindow();
}

function completeSpeech({ openFollowup, greeting }) {
  speaking = false;
  if (greeting) greetingSpoken = true;
  stopAudio();
  if (openFollowup) {
    openFollowupWindow();
  } else {
    scheduleRecognitionRestart();
  }
}

async function playGeneratedAudio(blob, options) {
  activeAudioUrl = URL.createObjectURL(blob);
  activeAudio = new Audio(activeAudioUrl);
  activeAudio.preload = 'auto';
  activeAudio.onplaying = () => {
    speaking = true;
    setVoiceState('speaking');
    setHint('');
  };
  activeAudio.onended = () => completeSpeech(options);
  activeAudio.onerror = () => {
    setHint('La voce locale non è disponibile in questo momento.');
    completeSpeech(options);
  };

  try {
    await activeAudio.play();
  } catch (error) {
    if (error?.name === 'NotAllowedError') {
      setHint('La voce è pronta. Tocchi o clicchi una volta per consentire l’audio del browser.');
      installGestureRetry(async () => {
        try {
          if (activeAudio) await activeAudio.play();
        } catch (retryError) {
          console.warn('[JARVIS] Audio playback retry failed:', retryError);
          completeSpeech(options);
        }
      });
      return;
    }
    console.warn('[JARVIS] Audio playback failed:', error);
    setHint('La voce locale non è disponibile in questo momento.');
    completeSpeech(options);
  }
}

async function getPcmContext() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioContextCtor) throw new Error('Web Audio non supportato dal browser.');
  if (!pcmContext || pcmContext.state === 'closed') pcmContext = new AudioContextCtor();
  if (pcmContext.state === 'suspended') await pcmContext.resume();
  if (pcmContext.state !== 'running') {
    const error = new Error('Audio del browser non autorizzato.');
    error.name = 'NotAllowedError';
    throw error;
  }
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

async function playPcmStream(response, options) {
  if (!response.body?.getReader) {
    const blob = await response.blob();
    await playGeneratedAudio(blob, options);
    return;
  }

  const generation = pcmGeneration;
  const ctx = await getPcmContext();
  const sampleRate = Number(response.headers.get('X-Sample-Rate')) || 24000;
  const reader = response.body.getReader();
  let scheduledAt = ctx.currentTime + 0.035;
  let carry = new Uint8Array(0);
  let heardAnything = false;

  speaking = true;
  setVoiceState('speaking');
  setHint('');

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

  if (!heardAnything || generation !== pcmGeneration) {
    if (generation === pcmGeneration) completeSpeech(options);
    return;
  }

  const remainingMs = Math.max(0, (scheduledAt - ctx.currentTime) * 1000) + 60;
  window.setTimeout(() => {
    if (generation === pcmGeneration) completeSpeech(options);
  }, remainingMs);
}

async function fetchErrorDetail(response, fallback) {
  try {
    const payload = await response.json();
    return payload.detail || fallback;
  } catch {
    return fallback;
  }
}

async function speak(text, { openFollowup = true, greeting = false } = {}) {
  const content = String(text || '').trim();
  if (!content) {
    if (openFollowup) openFollowupWindow();
    return;
  }

  stopRecognition();
  stopAudio();
  followupDeadline = 0;
  speaking = true;
  setVoiceState('speaking');
  setHint('');

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
      throw new Error(await fetchErrorDetail(response, 'CosyVoice locale non disponibile.'));
    }

    if (!greeting && response.headers.get('X-Audio-Format') === 'pcm_s16le_mono') {
      await playPcmStream(response, { openFollowup, greeting });
      return;
    }

    const blob = await response.blob();
    if (!blob.size) throw new Error('Il motore vocale ha restituito un audio vuoto.');
    await playGeneratedAudio(blob, { openFollowup, greeting });
  } catch (error) {
    if (error?.name === 'AbortError') return;
    speaking = false;
    console.warn('[JARVIS] Local TTS:', error);
    if (error?.name === 'NotAllowedError') {
      setHint('Tocchi o clicchi una volta per autorizzare l’audio.');
    } else {
      // TTS and STT are independent: keep listening even when CosyVoice is not ready.
      setHint('Voce in preparazione. Il microfono resta disponibile.');
    }
    if (openFollowup) {
      openFollowupWindow();
    } else {
      scheduleRecognitionRestart();
    }
  }
}

window.addEventListener('jarvis:greeting', (event) => {
  if (greetingSpoken) return;
  const text = String(event?.detail?.text || '').trim();
  if (!text) return;
  speak(text, { openFollowup: true, greeting: true });
});

window.addEventListener('jarvis:reply-ready', (event) => {
  speak(event?.detail?.text || '', { openFollowup: true, greeting: false });
});

// Browser voice input must not depend on the TTS engine being available. Start
// permission/listening on the first normal user interaction with the page.
const bootstrapVoice = () => {
  document.removeEventListener('pointerdown', bootstrapVoice, true);
  document.removeEventListener('keydown', bootstrapVoice, true);
  startVoiceSession();
};
document.addEventListener('pointerdown', bootstrapVoice, true);
document.addEventListener('keydown', bootstrapVoice, true);

window.addEventListener('beforeunload', () => {
  voiceSessionStarted = false;
  stopRecognition();
  stopAudio();
  if (pcmContext && pcmContext.state !== 'closed') {
    pcmContext.close().catch(() => {});
  }
});
