let recognition = null;
let recognitionRunning = false;
let followupDeadline = 0;
let submitted = false;
let speaking = false;
let greetingSpoken = false;
let retryOnGestureInstalled = false;
let activeAudio = null;
let activeAudioUrl = '';
let pcmContext = null;
let pcmAbortController = null;
let pcmGeneration = 0;
const pcmSources = new Set();

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const FOLLOWUP_MS = 12000;
const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');

function setHint(text) {
  const hint = document.querySelector('.hint');
  if (hint) hint.textContent = text || '';
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
  } catch {
    return false;
  }
}

function startRecognitionWindow() {
  if (!RecognitionCtor || recognitionRunning || speaking) return;
  if (Date.now() >= followupDeadline) {
    setHint('In attesa, signore.');
    return;
  }

  submitted = false;
  recognition = new RecognitionCtor();
  recognition.lang = 'it-IT';
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognitionRunning = true;
    setHint('La ascolto, signore.');
  };

  recognition.onresult = (event) => {
    let text = '';
    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      if (result?.isFinal) text += result?.[0]?.transcript || '';
    }
    text = text.trim();
    if (!text || submitted) return;

    submitted = true;
    stopRecognition();
    setHint('');
    emitVoiceInput(text);
  };

  recognition.onerror = (event) => {
    recognitionRunning = false;
    if (event.error === 'aborted') return;
    if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
      setHint('Il browser richiede il permesso al microfono. Tocchi o clicchi una volta sulla pagina.');
      installGestureRetry(() => openFollowupWindow(FOLLOWUP_MS));
      return;
    }
    if (event.error !== 'no-speech') {
      console.warn('[JARVIS] Speech recognition:', event.error);
    }
  };

  recognition.onend = () => {
    recognitionRunning = false;
    recognition = null;
    if (!submitted && !speaking && Date.now() < followupDeadline) {
      window.setTimeout(startRecognitionWindow, 250);
    } else if (!submitted && Date.now() >= followupDeadline) {
      setHint('In attesa, signore.');
    }
  };

  try {
    recognition.start();
  } catch (error) {
    recognitionRunning = false;
    recognition = null;
    console.warn('[JARVIS] Unable to start recognition:', error);
  }
}

async function openFollowupWindow(duration = FOLLOWUP_MS) {
  if (!RecognitionCtor) {
    setHint('La conversazione vocale automatica richiede Chrome o Edge aggiornato.');
    return;
  }

  followupDeadline = Date.now() + duration;
  const allowed = await ensureMicPermission();
  if (!allowed) {
    setHint('Consenta l’accesso al microfono. Dopo il primo permesso JARVIS non avrà bisogno di pulsanti.');
    installGestureRetry(() => openFollowupWindow(duration));
    return;
  }
  startRecognitionWindow();
}

function completeSpeech({ openFollowup, greeting }) {
  speaking = false;
  if (greeting) greetingSpoken = true;
  stopAudio();
  if (openFollowup) openFollowupWindow();
}

async function playGeneratedAudio(blob, options) {
  activeAudioUrl = URL.createObjectURL(blob);
  activeAudio = new Audio(activeAudioUrl);
  activeAudio.preload = 'auto';
  activeAudio.onplaying = () => {
    speaking = true;
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
  setHint('');

  try {
    // Opening audio uses a complete WAV so browsers can retry the same clip if
    // autoplay is blocked. Conversational replies use raw PCM streaming and
    // begin playing as soon as CosyVoice produces the first chunk.
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
      setHint('Voce locale in attesa del campione vocale.');
    }
    if (openFollowup) openFollowupWindow();
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

window.addEventListener('beforeunload', () => {
  stopRecognition();
  stopAudio();
  if (pcmContext && pcmContext.state !== 'closed') {
    pcmContext.close().catch(() => {});
  }
});
