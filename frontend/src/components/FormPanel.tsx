/**
 * A form opened from a page, in the side panel (frontend-plan §6.9) instead of a box
 * in the middle of the page. The form inside keeps its own fields and buttons;
 * Escape or the close button calls `onClose`, and focus returns to what opened it.
 *
 * For a form whose footer is the standard *Cancel* and one primary button, use
 * `SidePanel`, which also places a refusal on its field.
 */

import { Sheet } from './ui/Dialog';

export function FormPanel({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={title}
    >
      {children}
    </Sheet>
  );
}
