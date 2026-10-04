import { useState } from 'react';

import { Icon, type IconComponent } from '@/design/icons';

import { applyTheme, readStoredTheme, storeTheme, type Theme } from './theme';

/** The step after each theme: system -> light -> dark -> system. */
const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };

const LOOK: Record<Theme, { icon: IconComponent; label: string }> = {
  system: { icon: Icon.themeSystem, label: 'System' },
  light: { icon: Icon.themeLight, label: 'Light' },
  dark: { icon: Icon.themeDark, label: 'Dark' },
};

/** One button that steps through system -> light -> dark. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const next = NEXT[theme];
  const Glyph = LOOK[theme].icon;

  return (
    <button
      type="button"
      onClick={() => {
        setTheme(next);
        storeTheme(next);
        applyTheme(next);
      }}
      aria-label={`Theme: ${LOOK[theme].label}. Switch to ${LOOK[next].label}`}
      title={`Theme: ${LOOK[theme].label}`}
      className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-3 transition-colors hover:bg-sunken hover:text-ink"
    >
      <Glyph size={16} />
    </button>
  );
}
