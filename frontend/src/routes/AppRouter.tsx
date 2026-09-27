import { BrowserRouter, Route, Routes } from 'react-router-dom';

import { NotFound } from '@/components';
import { AppShell } from '@/layout/AppShell';
import {
  CompanyRoutes,
  DealDetailPage,
  FollowUpsPage,
  LegacyExporterRoutes,
  PipelinePage,
  QualificationCriteriaPage,
} from '@/modules/onboarding';
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
            <Route path="/settings/qualification-criteria" element={<QualificationCriteriaPage />} />
            <Route path="/exporters/*" element={<LegacyExporterRoutes />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
