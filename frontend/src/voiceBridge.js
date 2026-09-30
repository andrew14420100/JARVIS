// JARVIS browser voice bridge
//
// Microphone capture intentionally does NOT happen in the browser. The Siri-like
// Windows listener owns wake-word detection and microphone input, avoiding web
// permission prompts and short SpeechRecognition windows. Browser TTS playback
// is optional and disabled by default so it cannot duplicate the desktop audio.

let activeAudio = null;
let activeAudioUrl = '';
let pcmContext = null;
let pcmAbortController = null;
let pcmGeneration = 0;
const pcmSources = new Set();

const API_BASE = (process.env.REACT_APP_BACKEND_URL || '').replace(/\/$/, '');
const BROWSER_TTS_ENABLED = String(process.env.REACT_APP_BROWSER_TTS_ENABLED || '').toLowerCase() === 'true';

function setHint(text) {
  const hint = document.querySelector('.hint');
  if (hint) hint.textContent = text || '';
}

function setVoiceState(state, detail = '') {
  window.dispatchEvent(new CustomEvent('jarvis:voice-state', {
    detail: { state, detail },
  }));
}

function stopAudio() {
  pcmGeneration += 1;
  if (pcmAbortController) {
    try {
      pcmAbortController.abort();
    } catch {
      // Request may already be closed.
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
      // Ignore media cleanup races.
    }
  }
  activeAudio = null;
  if (activeAudioUrl) URL.revokeObjectURL(activeAudioUrl);
  activeAudioUrl = '';
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
  if (!response.body?.getReader) return;

  stopAudio();
  const generation = pcmGeneration;
  const ctx = await getPcmContext();
  const sampleRate = Number(response.headers.get('X-Sample-Rate')) || 24000;
  const reader = response.body.getReader();
  let scheduledAt = ctx.currentTime + 0.035;
  let carry = new Uint8Array(0);

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
  }
}

async function playGeneratedAudio(blob) {
  stopAudio();
  activeAudioUrl = URL.createObjectURL(blob);
  activeAudio = new Audio(activeAudioUrl);
  activeAudio.preload = 'auto';
  activeAudio.onplaying = () => setVoiceState('speaking');
  activeAudio.onended = () => setVoiceState('desktop-listener');
  await activeAudio.play();
}

async function speak(text, { greeting = false } = {}) {
  if (!BROWSER_TTS_ENABLED) {
    setVoiceState('desktop-listener');
    return;
  }

  const content = String(text || '').trim();
  if (!content) return;

  try {
    const endpoint = greeting ? '/api/tts' : '/api/tts/stream';
    pcmAbortController = new AbortController();
    const response = await fetch(`${API_BASE}${endpoint}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: content }),
      signal: pcmAbortController.signal,
    });
    if (!response.ok) return;

    if (!greeting && response.headers.get('X-Audio-Format') === 'pcm_s16le_mono') {
      await playPcmStream(response);
      return;
    }

    const blob = await response.blob();
    if (blob.size) await playGeneratedAudio(blob);
  } catch (error) {
    if (error?.name !== 'AbortError') {
      console.warn('[JARVIS] Browser TTS:', error);
    }
  }
}

window.addEventListener('jarvis:greeting', (event) => {
  speak(event?.detail?.text || '', { greeting: true });
});

window.addEventListener('jarvis:reply-ready', (event) => {
  speak(event?.detail?.text || '', { greeting: false });
});

// The desktop listener is the microphone owner. This is informational only and
// never calls getUserMedia/SpeechRecognition, so Emergent cannot trigger a web
// microphone permission prompt.
setVoiceState('desktop-listener');
setHint('Listener vocale desktop in standby: dica “Jarvis”.');

window.addEventListener('beforeunload', () => {
  stopAudio();
  if (pcmContext && pcmContext.state !== 'closed') {
    pcmContext.close().catch(() => {});
  }
});
