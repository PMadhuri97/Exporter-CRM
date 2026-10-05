import type { Config } from 'tailwindcss';

// Design tokens — a standard enterprise palette (docs/frontend-plan.md §5): neutral
// greys, one brand blue for what can be acted on, and colour otherwise spent only on
// state. Consumed by name (`bg-positive-tint`, `text-ink-3`, `bg-accent-solid`)
// rather than as ad hoc values,
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
 * (`bg-positive-tint`) and dot/fill (`bg-positive-solid`). */
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
  // first paint by the inline script in index.html). Light is the default.
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        // Neutrals: the page (`paper`), cards (`surface`), lines and text.
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
        // The brand colour, for actions only (§5.2): links and accent text, the
        // primary button's fill and its hover, and the selected row's tint.
        accent: {
          DEFAULT: token('accent'),
          solid: token('accent-solid'),
          'solid-hover': token('accent-solid-hover'),
          tint: token('accent-tint'),
        },
        // State: each hue spent once.
        positive: meaning('positive'),
        negative: meaning('negative'),
        attention: meaning('attention'),
        progress: meaning('progress'),
        idle: meaning('idle'),
      },
      fontFamily: {
        // One family, the operating system's UI font (§5.3): Segoe UI on Windows, as
        // Dynamics 365 draws, and San Francisco on macOS. Nothing to download, and it
        // has the rupee sign.
        sans: [
          '"Segoe UI Variable Text"',
          '"Segoe UI"',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          '"Helvetica Neue"',
          'Arial',
          'sans-serif',
        ],
      },
      fontSize: {
        // §5.3: weight, not a second face, sets the hierarchy.
        caption: ['0.75rem', { lineHeight: '1rem' }], // 12/16: labels above values
        secondary: ['0.8125rem', { lineHeight: '1.125rem' }], // 13/18: facts lines, metadata
        body: ['0.875rem', { lineHeight: '1.25rem' }], // 14/20: the default
        heading: ['1rem', { lineHeight: '1.375rem' }], // 16/22: card titles
        title: ['1.25rem', { lineHeight: '1.75rem' }], // 20/28: page and record titles
        count: ['1.5rem', { lineHeight: '2rem' }], // 24/32: Home counts
      },
      boxShadow: {
        // §5.5: resting surfaces have a border and no shadow; only floating layers
        // (menus, popovers, search results, dialogs, the side panel) get this one.
        float: 'var(--shadow-float)',
      },
      borderRadius: {
        // §5.5: 4 for controls, badges and cards; 8 for dialogs, the side panel and
        // menus. The stock names are re-pointed so existing classes land on the scale.
        sm: '4px',
        DEFAULT: '4px',
        md: '4px',
        lg: '4px',
        xl: '8px',
        '2xl': '8px',
      },
      transitionDuration: {
        quick: 'var(--dur-quick)',
        pop: 'var(--dur-pop)',
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
      },
      animation: {
        'fade-in': 'fade-in var(--dur-quick) cubic-bezier(.2,.8,.2,1)',
        'slide-in-left': 'slide-in-left var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'slide-in-right': 'slide-in-right var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'slide-in-up': 'slide-in-up var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'pop-in': 'pop-in var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
        'float-in': 'float-in var(--dur-pop) cubic-bezier(.2,.8,.2,1)',
      },
      maxWidth: {
        // A cap for pages that read as one column (sign-in excepted); record pages
        // use the full width (§5.4).
        reading: '77.5rem',
      },
    },
  },
  plugins: [],
} satisfies Config;
