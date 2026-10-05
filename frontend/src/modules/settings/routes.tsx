// modules/settings: route subtree, mounted by the app router as
// `<Route path="/settings/*" element={<SettingsRoutes />} />`. The page owns the
// section routes (`profile`, `users`, `roles`) so the whole settings frame is one
// lazily loaded chunk, matching modules/onboarding's shape.
import { lazy, type ReactNode } from 'react';
import { Route, Routes } from 'react-router-dom';

import type { SettingsSection } from './pages/SettingsPage';

// Loaded on first use, like every other screen.
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsPage })),
);

// The Settings frame for a section another module owns (Qualification criteria,
// Required documents): loaded on first use too, so Settings never joins the first
// download.
const SettingsFrame = lazy(() =>
  import('./pages/SettingsPage').then((m) => ({ default: m.SettingsFrame })),
);

export function SettingsSectionFrame({ section, children }: { section: SettingsSection; children: ReactNode }) {
  return <SettingsFrame section={section}>{children}</SettingsFrame>;
}

export function SettingsRoutes() {
  return (
    <Routes>
      <Route path="*" element={<SettingsPage />} />
    </Routes>
  );
}
