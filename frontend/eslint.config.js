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
export default tseslint.config(
  { ignores: ['dist', 'src/lib/api/schema.ts'] },
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
        {
          type: 'module',
          pattern: 'src/modules/*',
          mode: 'folder',
          capture: ['moduleName'],
        },
        { type: 'platform', pattern: 'src/platform/*', mode: 'folder' },
        { type: 'app', pattern: 'src/{routes,layout,pages,lib,test}/**' },
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
      // restriction at all (two rules below); `app`/`platform` stay
      // unrestricted, since nothing in the ticket doc calls for gating
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
      'boundaries/entry-point': [
        'error',
        {
          default: 'allow',
          rules: [
            { target: 'module', disallow: '*' },
            { target: 'module', allow: 'index.ts' },
          ],
        },
      ],
    },
  },
);
