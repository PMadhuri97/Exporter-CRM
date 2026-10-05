/**
 * Generic UI shared across screens — no domain knowledge, no owner.
 *
 * The test for belonging here is that a component knows nothing about
 * companies, gauges or deals: `DetailRow` renders a label and a value,
 * whatever they are. Domain components (the journey and marker tags, the
 * marker control) stay under `modules/onboarding/components/`.
 *
 * `ui/` holds the primitives every screen is built from — buttons, tags,
 * segmented choices, popovers, sheets, dialogs, inline edits and form fields —
 * so a screen composes them rather than repeating long class strings that
 * drift apart one edit at a time. The tokens they draw with, the icon map and
 * the brand mark live in `src/design/` (frontend-plan §5).
 */

export { DetailRow } from './DetailRow';
export { EmptySection } from './EmptySection';
export { FormPanel } from './FormPanel';

export { Button, type ButtonProps } from './ui/Button';
export { Card, Panel } from './ui/Card';
export { Composer } from './ui/Composer';
export { composerFieldError } from './ui/composerFieldError';
export { DatePopover } from './ui/DatePopover';
export { ConfirmDialog, Dialog, Sheet } from './ui/Dialog';
export { Editable, type EditableOption } from './ui/Editable';
export { ErrorState } from './ui/ErrorState';
export { Count, EmptyLine, InlineError, Kbd } from './ui/Feedback';
export { Field, FormError, Input, Select, Textarea } from './ui/Field';
export { NOT_FOUND_TITLE, NotFound } from './ui/NotFound';
export { PageHeader } from './ui/PageHeader';
export {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
  Popover,
  PopoverAnchor,
  PopoverClose,
  PopoverContent,
  PopoverTrigger,
} from './ui/Popover';
export { Segmented, type SegmentedOption } from './ui/Segmented';
export { Skeleton } from './ui/Skeleton';
export {
  buttonClasses,
  LINK_CLASSES,
  TAG_DOT_CLASSES,
  TAG_TONE_CLASSES,
  type ButtonSize,
  type ButtonVariant,
  type TagTone,
} from './ui/styles';
export { Tabs, TabsContent, TabsList, TabsTrigger } from './ui/Tabs';
export { Tag, type TagProps } from './ui/Tag';
export { useSearchParamState } from './ui/useSearchParamState';
