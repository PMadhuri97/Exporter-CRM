import { describe, expect, it } from 'vitest';

import { nextMinuteForDateTimeInput } from './format';

describe('nextMinuteForDateTimeInput', () => {
  it("reads the person's own clock, not UTC", () => {
    // Built from local parts, so the expected string is too: whatever zone the test
    // runs in, the floor must match what a datetime-local input shows for that moment.
    const now = new Date(2026, 9, 7, 14, 5, 30);
    expect(nextMinuteForDateTimeInput(now)).toBe('2026-10-07T14:06');
  });

  it('is the next minute, so the current one — already seconds old — is not offered', () => {
    const now = new Date(2026, 9, 7, 14, 5, 0);
    expect(nextMinuteForDateTimeInput(now)).toBe('2026-10-07T14:06');
  });

  it('rolls over the hour, the day and the year', () => {
    expect(nextMinuteForDateTimeInput(new Date(2026, 11, 31, 23, 59, 10))).toBe('2027-01-01T00:00');
  });

  it('pads single digits, as the input requires', () => {
    expect(nextMinuteForDateTimeInput(new Date(2026, 0, 2, 3, 4, 0))).toBe('2026-01-02T03:05');
  });
});
