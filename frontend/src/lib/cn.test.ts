import { describe, expect, it } from 'vitest';

import { cn } from './cn';

describe('cn', () => {
  it('keeps a colour and a size from the type scale side by side', () => {
    expect(cn('text-ink-2', 'text-secondary')).toBe('text-ink-2 text-secondary');
    expect(cn('text-caption text-negative')).toBe('text-caption text-negative');
  });

  it('still lets a later size or colour replace an earlier one', () => {
    expect(cn('text-body', 'text-caption')).toBe('text-caption');
    expect(cn('text-ink-2', 'text-ink')).toBe('text-ink');
  });
});
