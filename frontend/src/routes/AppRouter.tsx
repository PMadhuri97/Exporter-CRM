import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/layout/AppShell';
import { OnboardingRoutes, PipelinePage } from '@/modules/onboarding';
import { DashboardPlaceholder } from '@/pages/DashboardPlaceholder';
import { LoginPage } from '@/pages/auth/LoginPage';

import { ProtectedRoute } from './ProtectedRoute';

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<DashboardPlaceholder />} />
            <Route path="/exporters/*" element={<OnboardingRoutes />} />
            <Route path="/pipeline" element={<PipelinePage />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
