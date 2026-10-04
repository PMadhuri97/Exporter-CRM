import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { NotFound } from '@/components';
import { AppShell } from '@/layout/AppShell';
import { LoginPage } from '@/pages/auth/LoginPage';
import { Gate, NoWorkspace } from '@/platform/access';

import { APP_MODULES } from './modules';
import { ProtectedRoute } from './ProtectedRoute';

/**
 * Every route, generated from the module table (`./modules.ts`). Each module renders
 * inside its `Gate`, so a role without it gets `NotFound` — the same screen as an
 * address that does not exist — and never loads the module's code.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
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
