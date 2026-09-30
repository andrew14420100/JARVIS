let recognition = null;
let recognitionRunning = false;
let followupDeadline = 0;
let submitted = false;
let speaking = false;
let greetingSpoken = false;
let retryOnGestureInstalled = false;
let activeAudio = null;
let activeAudioUrl = '';

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
  stopAudio();
  activeAudioUrl = URL.createObjectURL(blob);
  activeAudio = new Audio(activeAudioUrl);
  activeAudio.preload = 'auto';
  activeAudio.onplaying = () => {
    speaking = true;
    setHint('');
  };
  activeAudio.onended = () => completeSpeech(options);
  activeAudio.onerror = () => {
    setHint('La voce non è disponibile in questo momento.');
    completeSpeech(options);
  };

  try {
    await activeAudio.play();
  } catch (error) {
    // Browsers can block the first unsolicited audio playback. Keep the Fish
    // audio already generated and retry the exact same clip on the first gesture.
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
    setHint('La voce non è disponibile in questo momento.');
    completeSpeech(options);
  }
}

async function speak(text, { openFollowup = true, greeting = false } = {}) {
  const content = String(text || '').trim();
  if (!content) {
    if (openFollowup) openFollowupWindow();
    return;
  }

  stopRecognition();
  followupDeadline = 0;
  speaking = true;
  setHint('');

  try {
    const response = await fetch(`${API_BASE}/api/tts`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: content }),
    });

    if (!response.ok) {
      let detail = 'Fish Audio S2 Pro non disponibile.';
      try {
        const payload = await response.json();
        detail = payload.detail || detail;
      } catch {
        // Keep the generic error.
      }
      throw new Error(detail);
    }

    const blob = await response.blob();
    if (!blob.size) throw new Error('Fish Audio ha restituito un audio vuoto.');
    await playGeneratedAudio(blob, { openFollowup, greeting });
  } catch (error) {
    speaking = false;
    console.warn('[JARVIS] Fish S2 TTS:', error);
    setHint('La voce Fish S2 è temporaneamente non disponibile.');
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
});
