import { Monitor, Moon, Sun } from 'lucide-react';
import { useState } from 'react';

import { applyTheme, readStoredTheme, storeTheme, type Theme } from './theme';

/** The step after each theme: system -> light -> dark -> system. */
const NEXT: Record<Theme, Theme> = { system: 'light', light: 'dark', dark: 'system' };

const LOOK: Record<Theme, { icon: typeof Sun; label: string }> = {
  system: { icon: Monitor, label: 'System' },
  light: { icon: Sun, label: 'Light' },
  dark: { icon: Moon, label: 'Dark' },
};

/** One button that steps through system -> light -> dark. */
export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(readStoredTheme);
  const next = NEXT[theme];
  const Icon = LOOK[theme].icon;

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
      className="flex h-8 w-8 items-center justify-center rounded-lg text-ink-faint transition-colors hover:bg-surface-sunken hover:text-ink"
    >
      <Icon size={16} />
    </button>
  );
}
