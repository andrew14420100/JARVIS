let recognition = null;
let recognitionRunning = false;
let suppressNextMicClick = false;
let awaitingVoiceReply = false;
let submittedCurrentUtterance = false;
let lastObservedReply = '';

const RecognitionCtor = window.SpeechRecognition || window.webkitSpeechRecognition;

function setReactInputValue(input, value) {
  const descriptor = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
  if (descriptor?.set) {
    descriptor.set.call(input, value);
  } else {
    input.value = value;
  }
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
}

function stopVisualMicrophone() {
  const mic = document.querySelector('.mic.active');
  if (!mic) return;
  suppressNextMicClick = true;
  mic.click();
}

function submitTranscript(text) {
  const normalized = String(text || '').trim();
  if (!normalized) return;

  const input = document.querySelector('.command input');
  const form = document.querySelector('form.command');
  if (!input || !form) return;

  setReactInputValue(input, normalized);
  awaitingVoiceReply = true;

  window.setTimeout(() => {
    if (typeof form.requestSubmit === 'function') {
      form.requestSubmit();
    } else {
      form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    }
  }, 70);
}

function chooseItalianVoice() {
  const voices = window.speechSynthesis?.getVoices?.() || [];
  return (
    voices.find((voice) => /^it[-_]/i.test(voice.lang) && /male|cosimo|diego|luca|marco/i.test(voice.name)) ||
    voices.find((voice) => /^it[-_]/i.test(voice.lang)) ||
    null
  );
}

function speakReply(text) {
  if (!window.speechSynthesis || !window.SpeechSynthesisUtterance) return;
  const content = String(text || '').trim();
  if (!content) return;

  window.speechSynthesis.cancel();
  const utterance = new SpeechSynthesisUtterance(content);
  utterance.lang = 'it-IT';
  utterance.rate = 1.02;
  utterance.pitch = 0.92;
  utterance.volume = 1;
  const voice = chooseItalianVoice();
  if (voice) utterance.voice = voice;
  window.speechSynthesis.speak(utterance);
}

function updateInterimText(text) {
  const input = document.querySelector('.command input');
  if (!input) return;
  setReactInputValue(input, text);
}

function startRecognition() {
  if (!RecognitionCtor || recognitionRunning) return;

  submittedCurrentUtterance = false;
  recognition = new RecognitionCtor();
  recognition.lang = 'it-IT';
  recognition.continuous = false;
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  recognition.onstart = () => {
    recognitionRunning = true;
  };

  recognition.onresult = (event) => {
    let interim = '';
    let finalText = '';

    for (let index = event.resultIndex; index < event.results.length; index += 1) {
      const result = event.results[index];
      const transcript = result?.[0]?.transcript || '';
      if (result.isFinal) finalText += transcript;
      else interim += transcript;
    }

    const visible = (finalText || interim).trim();
    if (visible) updateInterimText(visible);

    if (finalText.trim() && !submittedCurrentUtterance) {
      submittedCurrentUtterance = true;
      const command = finalText.trim();
      try {
        recognition.stop();
      } catch {
        // Recognition may already be stopping.
      }
      stopVisualMicrophone();
      submitTranscript(command);
    }
  };

  recognition.onerror = (event) => {
    recognitionRunning = false;
    if (event.error === 'aborted' && submittedCurrentUtterance) return;
    stopVisualMicrophone();
    const hint = document.querySelector('.hint');
    if (hint) {
      const reason = event.error === 'not-allowed'
        ? 'Permesso microfono negato dal browser.'
        : `Riconoscimento vocale non disponibile: ${event.error}.`;
      hint.textContent = reason;
    }
  };

  recognition.onend = () => {
    recognitionRunning = false;
    recognition = null;
    if (!submittedCurrentUtterance) stopVisualMicrophone();
  };

  try {
    window.speechSynthesis?.cancel?.();
    recognition.start();
  } catch (error) {
    recognitionRunning = false;
    recognition = null;
    console.warn('[JARVIS] Browser speech recognition failed:', error);
  }
}

function stopRecognition() {
  if (!recognition) return;
  try {
    recognition.abort();
  } catch {
    // Ignore a browser race while closing recognition.
  }
  recognition = null;
  recognitionRunning = false;
}

function installMicBridge() {
  document.addEventListener('click', (event) => {
    const button = event.target?.closest?.('.mic');
    if (!button) return;

    if (suppressNextMicClick) {
      suppressNextMicClick = false;
      return;
    }

    if (!RecognitionCtor) {
      const hint = document.querySelector('.hint');
      if (hint) hint.textContent = 'Il browser non supporta SpeechRecognition. Usa Chrome/Edge aggiornato.';
      return;
    }

    if (recognitionRunning) {
      stopRecognition();
      return;
    }

    window.setTimeout(startRecognition, 120);
  });
}

function installReplySpeaker() {
  const observer = new MutationObserver(() => {
    const reply = document.querySelector('.reply');
    if (!reply) return;
    const text = reply.textContent.trim();
    if (!text || text === lastObservedReply) return;
    lastObservedReply = text;

    if (awaitingVoiceReply) {
      awaitingVoiceReply = false;
      speakReply(text);
    }
  });

  observer.observe(document.documentElement, {
    childList: true,
    subtree: true,
    characterData: true,
  });
}

installMicBridge();
installReplySpeaker();
