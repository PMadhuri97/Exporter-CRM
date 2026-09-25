/**
 * Generic UI shared across screens — no domain knowledge, no owner.
 *
 * Everything here came out of `ExporterDetailPage.tsx` when that page was
 * split into per-owner panels. The test for belonging here is that a component
 * knows nothing about companies, gauges or deals: `DetailRow` renders a label
 * and a value, whatever they are.
 *
 * Domain components stay in their module. `StageChip` and
 * `LifecycleMoveControl` are about the journey, so they remain under
 * `modules/onboarding/components/`.
 */

export { DetailRow } from './DetailRow';
export { EmptySection } from './EmptySection';
export { FormPanel } from './FormPanel';
