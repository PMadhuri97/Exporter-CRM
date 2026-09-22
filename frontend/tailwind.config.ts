import type { Config } from 'tailwindcss';

// Design tokens implementing docs/exporter-crm-frontend-tickets.md's
// "quiet chrome, expressive data" principle and the semantic status
// language (lifecycle / verification / risk) — defined once here, consumed
// by name everywhere (`bg-status-passed`, `text-risk-high`, …) rather than
// as ad hoc hex values scattered per component.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Neutral chrome — restrained, one brand accent.
        brand: {
          50: '#f0fdfa',
          100: '#ccfbf1',
          400: '#2dd4bf',
          500: '#14b8a6',
          600: '#0d9488',
          900: '#134e4a',
        },
        surface: {
          DEFAULT: '#ffffff',
          subtle: '#f8fafc',
          sunken: '#f1f5f9',
        },
        ink: {
          DEFAULT: '#0f172a',
          muted: '#475569',
          faint: '#94a3b8',
        },
        border: {
          DEFAULT: '#e2e8f0',
          strong: '#cbd5e1',
        },
        // Lifecycle stage language (ExporterLifecycleStatus, grouped) —
        // gray -> blue -> green -> amber -> red, one hue family per stage
        // family, never reused for anything else on the same screen.
        stage: {
          new: '#64748b',
          contacted: '#64748b',
          onboarding: '#2563eb',
          approved: '#0d9488',
          active: '#16a34a',
          suspended: '#d97706',
          offboarded: '#94a3b8',
        },
        // VerificationResultStatus
        status: {
          passed: '#16a34a',
          failed: '#dc2626',
          review: '#d97706',
          pending: '#64748b',
        },
        // VerificationRiskLevel — never reused for lifecycle/status above,
        // so risk stays instantly scannable on a card that also shows both.
        risk: {
          low: '#16a34a',
          medium: '#d97706',
          high: '#dc2626',
        },
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'sans-serif',
        ],
      },
      fontFeatureSettings: {
        tabular: '"tnum" 1, "lnum" 1',
      },
      boxShadow: {
        // Soft borders over heavy shadows/gradients, per the design
        // principles — this is the one elevation shadow the whole app uses.
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
      },
      borderRadius: {
        lg: '0.625rem',
      },
    },
  },
  plugins: [],
} satisfies Config;
