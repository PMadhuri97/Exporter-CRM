/**
 * The colour theme — light, dark, or whatever the operating system prefers.
 *
 * Stored per browser: this is a viewing preference, not account data. Every
 * storage access is guarded, since storage can be unavailable (a private
 * window, blocked site data) and the app must render regardless. The same key
 * and rule are read by the inline script in `index.html`, which applies the
 * theme before React loads so a dark-theme viewer never sees a light flash.
 */

export type Theme = 'system' | 'light' | 'dark';

export const THEMES: readonly Theme[] = ['system', 'light', 'dark'];

export const THEME_STORAGE_KEY = 'aner.theme';

export function readStoredTheme(): Theme {
  try {
    const value = window.localStorage.getItem(THEME_STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    return 'system';
  }
}

export function storeTheme(theme: Theme): void {
  try {
    if (theme === 'system') window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Unavailable storage only means the choice lasts for this page view.
  }
}

/** `system` removes the attribute, handing the choice to the media query in
 * `index.css`. */
export function applyTheme(theme: Theme): void {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
}
