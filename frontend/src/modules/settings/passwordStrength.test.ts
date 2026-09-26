import { describe, expect, it } from 'vitest';

import { assessPassword } from './passwordStrength';

describe('assessPassword — policy gate', () => {
  it('accepts exactly what the backend accepts: 8+ chars, an uppercase and a digit', () => {
    // The same value used throughout the backend's own auth tests.
    const result = assessPassword('Password1');
    expect(result.meetsPolicy).toBe(true);
    expect(result.missing).toEqual([]);
  });

  it.each([
    ['alllowercase', 'an uppercase letter'],
    ['NoDigitsHere', 'a digit'],
    ['Ab1', 'at least 8 characters'],
  ])('refuses %s and names what is missing', (password, expected) => {
    const result = assessPassword(password);
    expect(result.meetsPolicy).toBe(false);
    expect(result.missing).toContain(expected);
  });

  it('does not require a symbol, because the server does not', () => {
    // A meter stricter than the policy would block a password the API would
    // happily accept.
    expect(assessPassword('Password1').meetsPolicy).toBe(true);
    expect(assessPassword('Password1!').meetsPolicy).toBe(true);
  });
});

describe('assessPassword — advisory score', () => {
  it('scores each satisfied check once', () => {
    expect(assessPassword('').score).toBe(0);
    expect(assessPassword('password').score).toBe(2); // length + lowercase
    expect(assessPassword('Password1!').score).toBe(5);
  });

  it('labels a too-short password by its length, not its variety', () => {
    // 'Ab1!' satisfies four checks but is unusable, so the label must lead
    // with the blocking problem.
    expect(assessPassword('Ab1!').label).toBe('Too short');
  });

  it.each([
    ['password', 'Weak'],
    ['password1', 'Fair'],
    ['Password1', 'Good'],
    ['Password1!', 'Strong'],
  ])('labels %s as %s', (password, label) => {
    expect(assessPassword(password).label).toBe(label);
  });
});
