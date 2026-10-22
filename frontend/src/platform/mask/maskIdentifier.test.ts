import { describe, expect, it } from 'vitest';

import { maskTail } from './maskIdentifier';

const PAN = 'ABCDE1234F';

/**
 * Who may reveal is no longer answered in this file. It is the server's permission
 * (`exporters:view_full_tax_id`), read on screen through `useCanRevealIdentifiers`, so
 * there is no role list here to drift from it — which is what happened when there was.
 */
describe('maskTail', () => {
  it('covers all but the last four characters', () => {
    expect(maskTail(PAN)).toBe('••••••234F');
  });

  it('covers a short value completely, leaving no four characters to read', () => {
    expect(maskTail('ABCD')).toBe('••••');
    expect(maskTail('AB')).toBe('••');
    expect(maskTail('A')).toBe('•');
  });

  it('leaves an already-masked value as it found it', () => {
    // The server masks before the value reaches the browser, and `Identifier` masks
    // again over the top; masking twice must not shift the bullets or the four
    // characters that are meant to stay readable.
    expect(maskTail('••••••234F')).toBe('••••••234F');
  });
});
