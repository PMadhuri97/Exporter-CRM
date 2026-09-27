import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { THEME_STORAGE_KEY } from './theme';
import { ThemeToggle } from './ThemeToggle';

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute('data-theme');
  window.localStorage.clear();
});

describe('ThemeToggle', () => {
  it('steps system -> light -> dark -> system, and remembers the choice', () => {
    render(<ThemeToggle />);
    const button = screen.getByRole('button', { name: /Theme: System/ });

    fireEvent.click(button);
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');

    fireEvent.click(button);
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark');

    fireEvent.click(button);
    // System hands the choice back to the media query.
    expect(document.documentElement).not.toHaveAttribute('data-theme');
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
  });

  it('still works when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole('button', { name: /Theme: System/ }));
    expect(document.documentElement).toHaveAttribute('data-theme', 'light');
  });
});
