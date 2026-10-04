// modules/settings: route subtree, mounted by the app router as
// `<Route path="/settings/*" element={<SettingsRoutes />} />`. Owning its own
// nested `<Routes>` keeps later additions (an audit tab, a criteria screen)
// inside this module, matching modules/onboarding's shape.
import { lazy } from 'react';
import { Route, Routes } from 'react-router-dom';

// Loaded on first use (frontend plan G7), like every other screen.
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);

export function SettingsRoutes() {
  return (
    <Routes>
      <Route index element={<SettingsPage />} />
    </Routes>
  );
}
