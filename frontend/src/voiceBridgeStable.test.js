import {
  isStandbyCommand,
  normalizeWakeTranscript,
  pcm16ToFloat32,
  routeTranscript,
} from './voiceBridgeStable';

describe('JARVIS stable browser voice policy', () => {
  test('requires Jarvis only for initial activation', () => {
    expect(routeTranscript('che ore sono', false)).toEqual({
      action: 'standby',
      active: false,
      command: '',
    });
    expect(routeTranscript('Jarvis', false)).toEqual({
      action: 'activate',
      active: true,
      command: '',
    });
  });

  test('keeps the conversation active without any timeout', () => {
    expect(routeTranscript('che ore sono?', true)).toEqual({
      action: 'submit',
      active: true,
      command: 'che ore sono?',
    });
    expect(routeTranscript('no aspetta, intendevo domani', true)).toEqual({
      action: 'submit',
      active: true,
      command: 'no aspetta, intendevo domani',
    });
  });

  test('strips activation phrase from an initial command', () => {
    expect(normalizeWakeTranscript('Hey Jarvis, apri FlixIT')).toEqual({
      activated: true,
      command: 'apri FlixIT',
    });
    expect(routeTranscript('Jarvis spiegami gli integrali', false)).toEqual({
      action: 'submit',
      active: true,
      command: 'spiegami gli integrali',
    });
  });

  test('explicit standby commands close the persistent session', () => {
    expect(isStandbyCommand('Jarvis, vai in standby')).toBe(true);
    expect(isStandbyCommand('chiudi la sessione')).toBe(true);
    expect(routeTranscript('torna in standby', true)).toEqual({
      action: 'deactivate',
      active: false,
      command: '',
    });
  });

  test('PCM conversion preserves signed 16-bit endpoints', () => {
    const bytes = new Uint8Array([0x00, 0x80, 0x00, 0x00, 0xff, 0x7f]);
    const values = pcm16ToFloat32(bytes);
    expect(values).toHaveLength(3);
    expect(values[0]).toBeCloseTo(-1, 6);
    expect(values[1]).toBeCloseTo(0, 6);
    expect(values[2]).toBeCloseTo(1, 6);
  });
});
