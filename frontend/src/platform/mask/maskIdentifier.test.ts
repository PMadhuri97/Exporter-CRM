import { describe, expect, it } from 'vitest';

import { canReveal, maskIdentifier } from './maskIdentifier';

const PAN = 'ABCDE1234F';

describe('maskIdentifier', () => {
  it('masks for OPERATIONS on a record the user does not own', () => {
    expect(maskIdentifier(PAN, { role: 'OPERATIONS', isOwner: false })).toBe(
      '••••••234F',
    );
  });

  it('does not mask for OPERATIONS on a record the user owns', () => {
    expect(maskIdentifier(PAN, { role: 'OPERATIONS', isOwner: true })).toBe(
      PAN,
    );
  });

  it('never masks for COMPLIANCE, regardless of ownership', () => {
    expect(maskIdentifier(PAN, { role: 'COMPLIANCE', isOwner: false })).toBe(
      PAN,
    );
  });

  it('never masks for ADMIN', () => {
    expect(maskIdentifier(PAN, { role: 'ADMIN' })).toBe(PAN);
  });

  it('always masks for DEVELOPER, even claiming ownership', () => {
    expect(maskIdentifier(PAN, { role: 'DEVELOPER', isOwner: true })).toBe(
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
    expect(canReveal('OPERATIONS', true)).toBe(true);
    expect(canReveal('OPERATIONS', false)).toBe(false);
    expect(canReveal('OPERATIONS')).toBe(false);
    expect(canReveal('DEVELOPER', true)).toBe(false);
    expect(canReveal('API_USER', true)).toBe(false);
  });
});
