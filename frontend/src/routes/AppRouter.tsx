import { lazy, Suspense } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { NotFound } from '@/components';
import { AppShell } from '@/layout/AppShell';
import { Gate, NoWorkspace } from '@/platform/access';

import { APP_MODULES } from './modules';
import { ProtectedRoute } from './ProtectedRoute';

/** Only a signed-out visitor needs the sign-in form (and its validation library). */
const LoginPage = lazy(() =>
  import('@/pages/auth/LoginPage').then((m) => ({ default: m.LoginPage })),
);

/**
 * The style guide (frontend-plan §12.4), in development only. `import.meta.env.DEV` is
 * the literal `false` in a production build, so this branch — and the dynamic import
 * inside it — is removed and the guide never reaches the bundle (checked on `dist/`).
 */
const StyleGuidePage = import.meta.env.DEV
  ? lazy(() =>
      import('@/design/styleguide/StyleGuidePage').then((m) => ({ default: m.StyleGuidePage })),
    )
  : null;

/**
 * Every route, generated from the module table (`./modules.ts`). Each module renders
 * inside its `Gate`, so a role without it gets `NotFound` — the same screen as an
 * address that does not exist — and never loads the module's code.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route
        path="/login"
        element={
          <Suspense fallback={null}>
            <LoginPage />
          </Suspense>
        }
      />
      {StyleGuidePage && (
        <Route
          path="/__design"
          element={
            <Suspense fallback={null}>
              <StyleGuidePage />
            </Suspense>
          }
        />
      )}
      <Route element={<ProtectedRoute />}>
        <Route element={<AppShell />}>
          {APP_MODULES.map(({ id, path, requires, Screen, denied }) => (
            <Route
              key={id}
              path={path}
              element={
                <Gate
                  requires={requires}
                  fallback={denied === 'noWorkspace' ? <NoWorkspace /> : undefined}
                >
                  <Screen />
                </Gate>
              }
            />
          ))}
          <Route path="*" element={<NotFound />} />
        </Route>
      </Route>
    </Routes>
  );
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <AppRoutes />
    </BrowserRouter>
  );
}
