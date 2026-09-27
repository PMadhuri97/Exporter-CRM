import type { Config } from 'tailwindcss';

// Design tokens — "quiet chrome, expressive data", one semantic status
// language defined once and consumed by name (`bg-status-passed`,
// `text-journey-prospect`, …) rather than as ad hoc values per component.
//
// Every colour is a CSS variable holding an RGB triplet, defined for the light
// and dark themes in `src/index.css`. `<alpha-value>` keeps Tailwind's opacity
// modifiers (`bg-status-passed/10`) working against a variable.
function token(name: string): string {
  return `rgb(var(--${name}) / <alpha-value>)`;
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // `data-theme="dark"` on <html> is set by `src/platform/theme` (and before the
  // first paint by the inline script in index.html).
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Neutral chrome — restrained, one brand accent.
        brand: {
          50: token('brand-50'),
          100: token('brand-100'),
          200: token('brand-200'),
          400: token('brand-400'),
          500: token('brand-500'),
          600: token('brand-600'),
          700: token('brand-700'),
          900: token('brand-900'),
        },
        surface: {
          DEFAULT: token('surface'),
          subtle: token('surface-subtle'),
          sunken: token('surface-sunken'),
        },
        ink: {
          DEFAULT: token('ink'),
          muted: token('ink-muted'),
          faint: token('ink-faint'),
        },
        border: {
          DEFAULT: token('border'),
          strong: token('border-strong'),
        },
        // The company journey (LEAD -> PROSPECT -> CUSTOMER): grey -> blue -> green.
        journey: {
          lead: token('journey-lead'),
          prospect: token('journey-prospect'),
          customer: token('journey-customer'),
        },
        // The relationship marker. NONE has no colour — it renders nothing.
        marker: {
          paused: token('marker-paused'),
          ended: token('marker-ended'),
        },
        // Outcome language shared by every gauge, check and scan result.
        status: {
          passed: token('status-passed'),
          failed: token('status-failed'),
          review: token('status-review'),
          pending: token('status-pending'),
          info: token('status-info'),
        },
        // Risk level — never reused for anything else on the same screen, so
        // risk stays instantly scannable.
        risk: {
          low: token('risk-low'),
          medium: token('risk-medium'),
          high: token('risk-high'),
        },
      },
      fontFamily: {
        sans: [
          '"Inter Variable"',
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
      },
      boxShadow: {
        // Soft borders over heavy shadows, per the design principles — the one
        // elevation the page uses, plus one for floating layers (dialogs, menus).
        card: 'var(--shadow-card)',
        overlay: 'var(--shadow-overlay)',
      },
      borderRadius: {
        lg: '0.625rem',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-in-left': {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        'pop-in': {
          from: { opacity: '0', transform: 'translate(-50%, -48%) scale(0.97)' },
          to: { opacity: '1', transform: 'translate(-50%, -50%) scale(1)' },
        },
      },
      animation: {
        'fade-in': 'fade-in 120ms ease-out',
        'slide-in-left': 'slide-in-left 160ms ease-out',
        'pop-in': 'pop-in 140ms ease-out',
      },
    },
  },
  plugins: [],
} satisfies Config;
