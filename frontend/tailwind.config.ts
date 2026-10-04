import type { Config } from 'tailwindcss';

// Design tokens — "Ink & Paper" (docs/frontend-plan.md §5): ink on paper, no
// brand hue, and colour spent only on meaning. Consumed by name
// (`bg-positive-tint`, `text-ink-3`, `border-line`) rather than as ad hoc values,
// and a lint rule (eslint.config.js) refuses Tailwind's raw palette and the
// retired token names, so a screen cannot drift back to `slate-*` or `violet-*`.
//
// Every colour is a CSS variable holding an RGB triplet, defined for the light
// and dark themes in `src/design/tokens.css`. `<alpha-value>` keeps Tailwind's
// opacity modifiers (`border-negative/30`) working against a variable.
function token(name: string): string {
  return `rgb(var(--${name}) / <alpha-value>)`;
}

/** A meaning's three roles: text/icon (`text-positive`), background
 * (`bg-positive-tint`) and dot/fill/lamp (`bg-positive-solid`). */
function meaning(name: string) {
  return {
    DEFAULT: token(name),
    tint: token(`${name}-tint`),
    solid: token(`${name}-solid`),
  };
}

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  // `data-theme="dark"` on <html> is set by `src/platform/theme` (and before the
  // first paint by the inline script in index.html).
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Neutrals: paper and ink.
        paper: token('paper'),
        surface: token('surface'),
        raised: token('raised'),
        sunken: token('sunken'),
        line: {
          DEFAULT: token('line'),
          strong: token('line-strong'),
        },
        ink: {
          DEFAULT: token('ink'),
          2: token('ink-2'),
          3: token('ink-3'),
          // Placeholders and decorative glyphs only — never text that must be read.
          4: token('ink-4'),
        },
        // Meaning: each hue spent once.
        positive: meaning('positive'),
        negative: meaning('negative'),
        attention: meaning('attention'),
        progress: meaning('progress'),
        idle: meaning('idle'),
      },
      fontFamily: {
        display: ['"Instrument Serif"', 'ui-serif', 'Georgia', 'serif'],
        sans: [
          '"Instrument Sans Variable"',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
        mono: ['"JetBrains Mono Variable"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      fontSize: {
        // §5.3: UI 15 lead · 14 body · 13 secondary · 12 caption; data 12.5.
        caption: ['0.75rem', { lineHeight: '1rem' }],
        secondary: ['0.8125rem', { lineHeight: '1.125rem' }],
        body: ['0.875rem', { lineHeight: '1.25rem' }],
        lead: ['0.9375rem', { lineHeight: '1.375rem' }],
        data: ['0.78125rem', { lineHeight: '1.125rem' }],
        // Display (serif): 20 · 24 · 30 · 40.
        'display-sm': ['1.25rem', { lineHeight: '1.625rem' }],
        'display-md': ['1.5rem', { lineHeight: '1.875rem' }],
        'display-lg': ['1.875rem', { lineHeight: '2.25rem' }],
        'display-xl': ['2.5rem', { lineHeight: '2.75rem' }],
      },
      boxShadow: {
        // Resting surfaces have hairlines and no shadow; only floating layers
        // (popover, menu, ⌘K, sheet, dialog) get this one.
        float: 'var(--shadow-float)',
      },
      borderRadius: {
        // §5.4: 4 tags · 6 controls · 10 sheets and popovers · 14 dialogs. The
        // stock names are re-pointed so existing classes land on the new scale.
        sm: '4px',
        DEFAULT: '4px',
        md: '6px',
        lg: '6px',
        xl: '10px',
        '2xl': '14px',
      },
      transitionDuration: {
        quick: 'var(--dur-quick)',
        pop: 'var(--dur-pop)',
        travel: 'var(--dur-travel)',
      },
      transitionTimingFunction: {
        enter: 'cubic-bezier(.2,.8,.2,1)',
        exit: 'cubic-bezier(.4,0,1,1)',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-in-left': {
          from: { transform: 'translateX(-100%)' },
          to: { transform: 'translateX(0)' },
        },
        'slide-in-right': {
          from: { transform: 'translateX(100%)' },
          to: { transform: 'translateX(0)' },
        },
        'slide-in-up': {
          from: { transform: 'translateY(100%)' },
          to: { transform: 'translateY(0)' },
        },
        'pop-in': {
          from: { opacity: '0', transform: 'translate(-50%, -48%) scale(0.98)' },
          to: { opacity: '1', transform: 'translate(-50%, -50%) scale(1)' },
        },
        'float-in': {
          from: { opacity: '0', transform: 'translateY(-2px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        // Rows arriving after a filter: a short rise into place.
        settle: {
          from: { opacity: '0', transform: 'translateY(3px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        // A stroke drawing itself (the sign-in page's journey line).
        draw: { to: { strokeDashoffset: '0' } },
      },
      animation: {
        'fade-in': 'fade-in var(--dur-quick) cubic-bezier(.2,.8,.2,1)',
        'slide-in-left': 'slide-in-left var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'slide-in-right': 'slide-in-right var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'slide-in-up': 'slide-in-up var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'pop-in': 'pop-in var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'float-in': 'float-in var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        settle: 'settle var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        // A file waiting on the scanner: slow, so it reads as "working", not "alarm".
        'scan-pulse': 'pulse 2.4s cubic-bezier(.4,0,.6,1) infinite',
      },
      maxWidth: {
        // Reading width for the dossier and the deal room (§5.4).
        reading: '77.5rem',
      },
    },
  },
  plugins: [],
} satisfies Config;
