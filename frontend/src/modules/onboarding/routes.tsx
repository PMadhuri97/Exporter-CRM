// modules/onboarding: route subtree — mounted by the app router as
// `<Route path="/exporters/*" element={<OnboardingRoutes />} />`. Owning its
// own nested `<Routes>` here (rather than the app router listing every
// onboarding path itself) keeps route additions inside this module as later
// tickets (Exporter Detail, etc.) land, matching the module-facade
// discipline elsewhere in this project.
import { Route, Routes } from 'react-router-dom';

import {
  AddExporterPage,
  CompanyImportPage,
  ExporterDetailPage,
  ExportersListPage,
  RxilIntakePage,
} from './pages';

export function OnboardingRoutes() {
  return (
    <Routes>
      <Route index element={<ExportersListPage />} />
      <Route path="new" element={<AddExporterPage />} />
      <Route path="import" element={<CompanyImportPage />} />
      <Route path="rxil-intake" element={<RxilIntakePage />} />
      <Route path=":customerId" element={<ExporterDetailPage />} />
    </Routes>
  );
}
