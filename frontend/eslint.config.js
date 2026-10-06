import js from '@eslint/js';
import boundaries from 'eslint-plugin-boundaries';
import reactHooks from 'eslint-plugin-react-hooks';
import reactRefresh from 'eslint-plugin-react-refresh';
import globals from 'globals';
import tseslint from 'typescript-eslint';

// Frontend equivalent of the backend's import-linter contracts
// (`backend/importlinter.ini`) — each `src/modules/<name>/` is a module
// whose only public surface is its own `index.ts`, matching the convention
// the empty scaffold's own comments already declared
// ("modules/onboarding — public facade. Other modules import ONLY from
// here."). `src/platform/**` (auth, the query client, the api client) is
// shared infrastructure every module may depend on, mirroring the backend's
// `app/platform/` split from `app/modules/`.
// Role checks live in one place, `src/platform/access`; see the block
// that uses these below.
const ROLE_SELECTORS = [
  {
    selector:
      "BinaryExpression[operator=/^[!=]==?$/][right.type='Literal'][right.value=/^(OPERATIONS|COMPLIANCE|ADMIN|DEVELOPER|API_USER)$/]",
    message: 'Role checks live in @/platform/access: use useCan(capability) or <Gate>.',
  },
  {
    selector:
      "BinaryExpression[operator=/^[!=]==?$/][left.type='Literal'][left.value=/^(OPERATIONS|COMPLIANCE|ADMIN|DEVELOPER|API_USER)$/]",
    message: 'Role checks live in @/platform/access: use useCan(capability) or <Gate>.',
  },
  {
    selector:
      "SwitchCase > Literal.test[value=/^(OPERATIONS|COMPLIANCE|ADMIN|DEVELOPER|API_USER)$/]",
    message: 'Role checks live in @/platform/access: use useCan(capability) or <Gate>.',
  },
];

// Ink & Paper (docs/frontend-plan.md §5): colour only ever means a
// state, and only through the tokens in tailwind.config.ts. These refuse, in any
// string or template literal, (1) Tailwind's raw palette (`text-slate-600`,
// `bg-violet-50`), (2) the retired token names (`text-ink-muted`,
// `bg-status-passed`, `border-border`, `shadow-card`, …), and (3) white or black
// fills that vanish in one of the two themes. Checked with a deliberate
// `bg-violet-50`, `text-brand-600` and `bg-white` in a probe file: each errors.
// A class starts the string or follows anything that cannot be part of a class name
// (a space, a quote, a variant's colon). esquery ends a regex at the first `/`, so a
// literal slash is written `\x2F`.
const UTILITY = String.raw`(^|[^\w-])(bg|text|border|ring|ring-offset|divide|outline|fill|stroke|from|via|to|placeholder|decoration|accent|caret|shadow)(-[trblxy])?-`;
const RAW_PALETTE =
  UTILITY +
  String.raw`(slate|gray|zinc|neutral|stone|violet|purple|indigo|emerald|teal|blue|red|amber|orange|green|yellow|lime|cyan|sky|fuchsia|pink|rose)-\d`;
const RETIRED_TOKEN =
  UTILITY +
  String.raw`(brand-\d|surface-(subtle|sunken)|ink-(muted|faint)|status-(passed|failed|review|pending|info)|journey-(lead|prospect|customer)|marker-(paused|ended)|risk-(low|medium|high)|border(-strong)?(?![\w-])|card(?![\w-])|overlay(?![\w-]))`;
const THEME_BLIND = String.raw`(^|[^\w-])(bg-white|text-black|bg-black(?!\x2F))(?![\w-])`;
// Icons come from one map, `src/design/icons.ts` (frontend-plan §5.5): lucide was the
// generated-UI default and is gone.
const ICON_IMPORTS = [
  { name: 'lucide-react', message: 'Use the Icon map from @/design/icons (frontend-plan §5.5).' },
];

const DESIGN_SELECTORS = [
  [RAW_PALETTE, 'Raw Tailwind palette classes are not part of Ink & Paper: use a token (text-ink-2, bg-positive-tint, border-line …) from tailwind.config.ts.'],
  [RETIRED_TOKEN, 'This token was retired: paper, sunken, line, ink-2/3, positive, negative, attention, progress, idle (docs/frontend-plan.md §5.2).'],
  [THEME_BLIND, 'White and black disappear in one of the two themes: use surface, paper or ink (text-paper on an ink fill).'],
].flatMap(([pattern, message]) => [
  { selector: `Literal[value=/${pattern}/]`, message },
  { selector: `TemplateElement[value.raw=/${pattern}/]`, message },
]);

export default tseslint.config(
  // Generated files: the API types and the icon shapes (scripts/build-icons.mjs).
  { ignores: ['dist', 'src/lib/api/schema.ts', 'src/design/icon-paths.ts'] },
  // Build scripts run in Node.
  { files: ['scripts/**/*.mjs'], languageOptions: { globals: globals.node } },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ['**/*.{ts,tsx}'],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
      boundaries,
    },
    settings: {
      // eslint-plugin-boundaries resolves each import via
      // eslint-module-utils to decide whether it's "local" (and therefore
      // subject to the rules below) at all — the default Node resolver
      // only knows .js/.json, so without this every `@/...` path-aliased
      // import (this whole project's convention) and every extension-less
      // relative import silently resolves to nothing, and the boundary
      // rules below no-op without ever reporting an error. Confirmed by
      // testing a deliberate violation before adding this — it was not
      // caught until this resolver was configured.
      'import/resolver': {
        typescript: { project: './tsconfig.app.json' },
      },
      'boundaries/elements': [
        // Each matches a whole folder — the plugin's default, so no `mode`.
        {
          type: 'module',
          pattern: 'src/modules/*',
          capture: ['moduleName'],
        },
        { type: 'platform', pattern: 'src/platform/*' },
        // `components` joined this list when ExporterDetailPage was split into
        // per-owner panels: the generic pieces it shared (DetailRow, EmptySection,
        // FormPanel) moved to src/components/, and a path matching no element type
        // is invisible to every rule below.
        { type: 'app', pattern: 'src/{routes,layout,pages,lib,test,components,design}/**' },
      ],
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_' },
      ],
      // The actual enforcement: a module may only be reached from outside via
      // its own index.ts — same discipline as the backend's per-module
      // `-internals-are-private` import-linter contracts. `default: 'allow'`
      // on purpose: only `module`-type targets get an entry-point
      // restriction at all (two policies below); `app`/`platform` stay
      // unrestricted, since nothing in the design calls for gating
      // them too. (A stricter "no module may import another module's
      // index.ts either" rule was considered and dropped — not specced,
      // and eslint-plugin-boundaries' same-type exception syntax for that
      // is easy to get subtly wrong.)
      //
      // Verified against a deliberate violation (importing
      // `modules/onboarding/constants.ts` directly from `src/routes/`) —
      // it was NOT caught until both the `import/resolver` setting above
      // AND both rules below (a bare `target: 'module', allow: 'index.ts'`
      // with `default: 'disallow'` also silently allowed every `app`/
      // `platform` import, since no rule's `target` matched them) were in
      // place. Re-run that check after touching this config.
      //
      // Written in eslint-plugin-boundaries v7's `dependencies` form (the old
      // `entry-point` rule, its `rules` option and string selectors are
      // deprecated). Imports within one module are not checked
      // (`checkInternals` defaults to false), exactly as `entry-point` behaved.
      // `'**'` rather than the old `'*'`: `'*'` matched only a module's top-level
      // files, so `modules/onboarding/components/X` slipped through. Checked with
      // `eslint --stdin --stdin-filename src/routes/_probe.tsx`: a top-level and a
      // nested internal import both error, the module's index does not.
      'boundaries/dependencies': [
        'error',
        {
          default: 'allow',
          policies: [
            {
              to: { element: { type: 'module' } },
              disallow: { to: { element: { fileInternalPath: '**' } } },
            },
            {
              to: { element: { type: 'module' } },
              allow: { to: { element: { fileInternalPath: 'index.ts' } } },
            },
          ],
        },
      ],
    },
  },
  // Who may use what is decided in one place: `src/platform/access`
  // (docs/frontend-plan.md §4.4). Anywhere else, comparing against a role name — or
  // switching on one — is a second copy of the server's role groups that can drift
  // from it, so it is refused here; ask `useCan(capability)` or wrap a route in
  // `<Gate>` instead. Tests are exempt: a role matrix has to name the roles.
  // Checked with a deliberate `user.role === 'ADMIN'` in a page: it errors.
  {
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/platform/access/**', '**/*.test.{ts,tsx}', 'src/test/**'],
    rules: {
      'no-restricted-syntax': ['error', ...ROLE_SELECTORS, ...DESIGN_SELECTORS],
      'no-restricted-imports': [
        'error',
        {
          paths: [
            {
              name: '@/platform/auth',
              importNames: ['isStaffRole', 'isAdminRole', 'isComplianceRole'],
              message: 'Replaced by useCan(capability) from @/platform/access.',
            },
            ...ICON_IMPORTS,
          ],
        },
      ],
    },
  },
  // `src/platform/access` may name roles (it is where they live) but draws with the
  // same tokens as everything else.
  {
    files: ['src/platform/access/**/*.{ts,tsx}'],
    ignores: ['**/*.test.{ts,tsx}'],
    rules: {
      'no-restricted-syntax': ['error', ...DESIGN_SELECTORS],
      'no-restricted-imports': ['error', { paths: ICON_IMPORTS }],
    },
  },
);
