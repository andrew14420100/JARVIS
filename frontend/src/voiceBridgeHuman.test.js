import { splitSpeechBuffer } from './voiceBridgeHuman';

describe('JARVIS human realtime speech buffering', () => {
  test('releases the first natural packet quickly without tiny fragments', () => {
    const result = splitSpeechBuffer('Molto bene, signore, sono qui. Sto controllando il resto', {
      firstPacket: true,
      final: false,
    });
    expect(result.segments[0]).toBe('Molto bene, signore, sono qui.');
    expect(result.rest).toBe('Sto controllando il resto');
    expect(result.firstPacket).toBe(false);
  });

  test('does not emit tiny meaningless fragments', () => {
    const result = splitSpeechBuffer('Va bene', { firstPacket: true, final: false });
    expect(result.segments).toEqual([]);
    expect(result.rest).toBe('Va bene');
  });

  test('flushes the remaining text when the model finishes', () => {
    const result = splitSpeechBuffer('Va bene, signore', { firstPacket: true, final: true });
    expect(result.segments).toEqual(['Va bene, signore']);
    expect(result.rest).toBe('');
  });

  test('cuts a long stream at a word boundary instead of starving TTS', () => {
    const text = 'Questa risposta continua abbastanza a lungo da superare la soglia iniziale senza ancora avere un punto finale';
    const result = splitSpeechBuffer(text, { firstPacket: true, final: false });
    expect(result.segments.length).toBeGreaterThan(0);
    expect(result.segments[0].length).toBeGreaterThanOrEqual(18);
    expect(result.segments[0].endsWith(' ')).toBe(false);
  });
});
