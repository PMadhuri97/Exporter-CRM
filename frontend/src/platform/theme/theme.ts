/**
 * The colour theme: light or dark (frontend-plan §5.2).
 *
 * Light is the default, and the operating system's preference does not switch it:
 * a demo laptop set to dark mode still shows the CRM in light. Dark is a choice in
 * the user menu, stored per browser — a viewing preference, not account data.
 * Every storage access is guarded, since storage can be unavailable (a private
 * window, blocked site data) and the app must render regardless. The same key and
 * rule are read by the inline script in `index.html`, which applies dark before
 * React loads so a dark-theme viewer never sees a light flash.
 */

export type Theme = 'light' | 'dark';

export const THEMES: readonly Theme[] = ['light', 'dark'];

export const THEME_STORAGE_KEY = 'aner.theme';

export function readStoredTheme(): Theme {
  try {
    return window.localStorage.getItem(THEME_STORAGE_KEY) === 'dark' ? 'dark' : 'light';
  } catch {
    return 'light';
  }
}

export function storeTheme(theme: Theme): void {
  try {
    if (theme === 'light') window.localStorage.removeItem(THEME_STORAGE_KEY);
    else window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Unavailable storage only means the choice lasts for this page view.
  }
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute('data-theme', theme);
}
