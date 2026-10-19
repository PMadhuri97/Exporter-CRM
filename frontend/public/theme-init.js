/* global window, document */
// Light is the default (src/platform/theme/theme.ts); apply a stored dark choice
// before first paint, so a dark-theme viewer never sees a light flash. A file rather
// than an inline <script>, so the Content-Security-Policy (security-headers.conf) can
// forbid inline script outright.
try {
  if (window.localStorage.getItem('aner.theme') === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
  }
} catch {
  // No storage: light applies.
}
