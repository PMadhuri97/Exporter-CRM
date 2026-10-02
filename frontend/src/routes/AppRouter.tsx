import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { NotFound } from '@/components';
import { AppShell } from '@/layout/AppShell';
import {
  CompanyRoutes,
  DealDetailPage,
  DealRequiredDocumentsPage,
  FollowUpsPage,
  LegacyExporterRoutes,
  PipelinePage,
  QualificationCriteriaPage,
} from '@/modules/onboarding';
import { SettingsRoutes } from '@/modules/settings';
import { LoginPage } from '@/pages/auth/LoginPage';
import { HomePage } from '@/pages/HomePage';

import { ProtectedRoute } from './ProtectedRoute';

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route element={<ProtectedRoute />}>
          <Route element={<AppShell />}>
            <Route path="/" element={<HomePage />} />
            <Route path="/companies/*" element={<CompanyRoutes />} />
            <Route path="/follow-ups" element={<FollowUpsPage />} />
            <Route path="/pipeline" element={<PipelinePage />} />
            <Route path="/deals/:dealId" element={<DealDetailPage />} />
            {/* `/settings/qualification-criteria` is a static path and
                `/settings/*` a splat, so React Router's ranking picks the
                specific one first whatever order they appear in here. */}
            <Route path="/settings/qualification-criteria" element={<QualificationCriteriaPage />} />
            <Route
              path="/settings/deal-required-documents"
              element={<DealRequiredDocumentsPage />}
            />
            <Route path="/settings/*" element={<SettingsRoutes />} />
            <Route path="/exporters/*" element={<LegacyExporterRoutes />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
