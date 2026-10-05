// modules/settings: route subtree, mounted by the app router as
// `<Route path="/settings/*" element={<SettingsRoutes />} />`. The page owns the
// section routes (`profile`, `users`, `roles`) so the whole settings frame is one
// lazily loaded chunk, matching modules/onboarding's shape.
import { lazy } from 'react';
import { Route, Routes } from 'react-router-dom';

// Loaded on first use, like every other screen.
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);

export function SettingsRoutes() {
  return (
    <Routes>
      <Route path="*" element={<SettingsPage />} />
    </Routes>
  );
}
