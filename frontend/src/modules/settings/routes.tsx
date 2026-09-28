// modules/settings: route subtree, mounted by the app router as
// `<Route path="/settings/*" element={<SettingsRoutes />} />`. Owning its own
// nested `<Routes>` keeps later additions (an audit tab, a criteria screen)
// inside this module, matching modules/onboarding's shape.
import { Route, Routes } from 'react-router-dom';

import { SettingsPage } from './pages';

export function SettingsRoutes() {
  return (
    <Routes>
      <Route index element={<SettingsPage />} />
    </Routes>
  );
}
