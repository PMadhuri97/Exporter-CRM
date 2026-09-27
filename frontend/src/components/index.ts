/**
 * Generic UI shared across screens — no domain knowledge, no owner.
 *
 * The test for belonging here is that a component knows nothing about
 * companies, gauges or deals: `DetailRow` renders a label and a value,
 * whatever they are. Domain components (the journey and marker chips, the
 * marker control) stay under `modules/onboarding/components/`.
 *
 * `ui/` holds the primitives every screen is built from — buttons, chips,
 * cards, tabs, dialogs, tables and form fields — so a screen composes them
 * rather than repeating long class strings that drift apart one edit at a time.
 */

export { DetailRow } from './DetailRow';
export { EmptySection } from './EmptySection';
export { FormPanel } from './FormPanel';

export { Button, type ButtonProps } from './ui/Button';
export { Card, Panel } from './ui/Card';
export { Chip } from './ui/Chip';
export { ConfirmDialog, Dialog, Drawer, Sheet } from './ui/Dialog';
export { ErrorState } from './ui/ErrorState';
export { Field, FormError, Input, Select, Textarea } from './ui/Field';
export { NotFound } from './ui/NotFound';
export { PageHeader } from './ui/PageHeader';
export { Skeleton } from './ui/Skeleton';
export {
  buttonClasses,
  CHIP_TONE_CLASSES,
  LINK_CLASSES,
  type ButtonSize,
  type ButtonVariant,
  type ChipTone,
} from './ui/styles';
export { Table, TBody, Td, Th, THead, Tr } from './ui/Table';
export { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/Tabs';
export { useSearchParamState } from './ui/useSearchParamState';
