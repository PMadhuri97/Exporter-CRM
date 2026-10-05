import { afterEach, describe, expect, it, vi } from 'vitest';

import { applyTheme, readStoredTheme, storeTheme, THEME_STORAGE_KEY } from './theme';

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute('data-theme');
  window.localStorage.clear();
});

describe('theme', () => {
  it('is light unless the viewer chose dark, whatever the system prefers', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList);
    expect(readStoredTheme()).toBe('light');
  });

  it('remembers dark, and forgets the choice on going back to light', () => {
    storeTheme('dark');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
    expect(readStoredTheme()).toBe('dark');

    storeTheme('light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    expect(readStoredTheme()).toBe('light');
  });

  it('marks the document with the theme', () => {
    applyTheme('dark');
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');
    applyTheme('light');
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  });

  it('falls back to light when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(readStoredTheme()).toBe('light');
    expect(() => storeTheme('dark')).not.toThrow();
  });
});
