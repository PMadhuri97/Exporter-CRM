/**
 * The shared last-activity clock behind the inactivity timeout: throttled writes, one
 * value for every tab, and a session with no recorded activity counted as timed out.
 */

import { beforeEach, describe, expect, it } from 'vitest';

import {
  clearActivity,
  hasTimedOut,
  lastActivityAt,
  msUntilIdleTimeout,
  recordActivity,
  recordActivityNow,
  setSessionIdleTimeout,
} from './sessionActivity';

beforeEach(() => {
  localStorage.clear();
  clearActivity();
});

describe('sessionActivity', () => {
  it('counts a session with no recorded activity as timed out', () => {
    expect(lastActivityAt()).toBeNull();
    expect(hasTimedOut()).toBe(true);
  });

  it('times out exactly one server timeout after the last activity', () => {
    setSessionIdleTimeout(30 * 60);
    recordActivityNow();
    const last = lastActivityAt()!;

    expect(msUntilIdleTimeout(last + 29 * 60_000)).toBe(60_000);
    expect(hasTimedOut(last + 30 * 60_000 - 1)).toBe(false);
    expect(hasTimedOut(last + 30 * 60_000)).toBe(true);
  });

  it('writes a burst of events once, but always writes a deliberate "I am here"', () => {
    recordActivity(1_000_000);
    recordActivity(1_001_000); // within the throttle: not written
    expect(lastActivityAt()).toBe(1_000_000);

    recordActivity(1_006_000);
    expect(lastActivityAt()).toBe(1_006_000);

    recordActivityNow();
    expect(lastActivityAt()).toBeGreaterThan(1_006_000);
  });

  it('is shared through localStorage, so another tab sees the same moment', () => {
    localStorage.setItem('aner.lastActivity', '12345');
    expect(lastActivityAt()).toBe(12345);
  });
});
