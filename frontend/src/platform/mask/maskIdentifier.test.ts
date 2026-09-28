import { describe, expect, it } from 'vitest';

import { canReveal, maskIdentifier } from './maskIdentifier';

const PAN = 'ABCDE1234F';

describe('maskIdentifier', () => {
  // Decision 12: sales staff see masked tax IDs. This used to be two tests —
  // masked for a non-owner, unmasked for the assigned relationship manager —
  // because `canReveal` carried an ownership exception. That exception is gone
  // on both sides, so ownership is no longer an input and there is one case.
  it('masks for OPERATIONS, owner or not', () => {
    expect(maskIdentifier(PAN, { role: 'OPERATIONS' })).toBe(
      '••••••234F',
    );
  });

  it('never masks for COMPLIANCE', () => {
    expect(maskIdentifier(PAN, { role: 'COMPLIANCE' })).toBe(
      PAN,
    );
  });

  it('never masks for ADMIN', () => {
    expect(maskIdentifier(PAN, { role: 'ADMIN' })).toBe(PAN);
  });

  it('always masks for DEVELOPER, even claiming ownership', () => {
    expect(maskIdentifier(PAN, { role: 'DEVELOPER' })).toBe(
      '••••••234F',
    );
  });

  it('always masks for API_USER', () => {
    expect(maskIdentifier(PAN, { role: 'API_USER' })).toBe('••••••234F');
  });

  it('passes through null/undefined unchanged, for any role', () => {
    expect(maskIdentifier(null, { role: 'OPERATIONS' })).toBeNull();
    expect(maskIdentifier(undefined, { role: 'COMPLIANCE' })).toBeNull();
  });

  it('masks a value no longer than the visible suffix entirely', () => {
    expect(maskIdentifier('AB', { role: 'OPERATIONS' })).toBe('••');
  });
});

describe('canReveal', () => {
  it('matches the capability matrix in docs/exporter-crm-frontend-tickets.md', () => {
    expect(canReveal('COMPLIANCE')).toBe(true);
    expect(canReveal('ADMIN')).toBe(true);
    expect(canReveal('OPERATIONS')).toBe(false);
    expect(canReveal('DEVELOPER')).toBe(false);
    expect(canReveal('API_USER')).toBe(false);
  });
});
