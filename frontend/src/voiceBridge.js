let recognition = null;
let recognitionRunning = false;
let followupDeadline = 0;
let submitted = false;
let speaking = false;
let greetingSpoken = false;
let retryOnGestureInstalled = false;

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;
const FOLLOWUP_MS = 12000;

function setHint(text) {
  const hint = document.querySelector('.hint');
  if (hint) hint.textContent = text || '';
}

function chooseItalianVoice() {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  return (
    voices.find((voice) => /^it[-_]/i.test(voice.lang) && /male|cosimo|diego|luca|marco|riccardo/i.test(voice.name)) ||
    voices.find((voice) => /^it[-_]/i.test(voice.lang)) ||
    null
  );
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
    setHint('Un momento, signore…');
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

function speak(text, { openFollowup = true, greeting = false } = {}) {
  const content = String(text || '').trim();
  if (!content) return;

  stopRecognition();
  followupDeadline = 0;

  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) {
    if (openFollowup) openFollowupWindow();
    return;
  }

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(content);
  utterance.lang = 'it-IT';
  utterance.rate = 0.96;
  utterance.pitch = 0.88;
  utterance.volume = 1;
  const voice = chooseItalianVoice();
  if (voice) utterance.voice = voice;

  let started = false;
  utterance.onstart = () => {
    started = true;
    speaking = true;
    setHint('');
  };

  utterance.onend = () => {
    speaking = false;
    if (greeting) greetingSpoken = true;
    if (openFollowup) openFollowupWindow();
  };

  utterance.onerror = () => {
    speaking = false;
    if (openFollowup) openFollowupWindow();
  };

  window.speechSynthesis.speak(utterance);

  // Some browsers block unsolicited speech until the first user gesture.
  window.setTimeout(() => {
    if (started) return;
    window.speechSynthesis.cancel();
    setHint('JARVIS è pronto. Tocchi o clicchi una volta sulla pagina per abilitare la voce del browser.');
    installGestureRetry(() => speak(content, { openFollowup, greeting }));
  }, 900);
}

window.addEventListener('jarvis:greeting', (event) => {
  if (greetingSpoken) return;
  speak(event?.detail?.text || 'Buongiorno, signore. Come sta oggi?', {
    openFollowup: true,
    greeting: true,
  });
});

window.addEventListener('jarvis:reply-ready', (event) => {
  speak(event?.detail?.text || '', { openFollowup: true, greeting: false });
});

window.addEventListener('beforeunload', () => {
  stopRecognition();
  window.speechSynthesis?.cancel?.();
});
