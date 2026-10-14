/**
 * Sorting a list the way File Explorer does: one **Sort** button with the two-way arrow,
 * opening a menu. Its first part is what to sort by, its second the direction —
 * *Ascending* or *Descending* — each with a dot on the current choice.
 *
 * Choosing a different column sorts by it in its natural first direction (A to Z for a
 * name, newest first for a date); the direction can then be turned round from the same
 * menu. The choice lives in the URL (`?sort=`, `?order=`; `useSortParams`), so a sorted
 * list can be shared and survives a reload.
 */

import * as Menu from '@radix-ui/react-dropdown-menu';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { buttonClasses, MENU_CONTENT, MENU_ITEM } from './styles';
import type { SortColumn, SortDirection, SortState } from './useSortParams';

const DIRECTION_LABEL: Record<SortDirection, string> = {
  asc: 'Ascending',
  desc: 'Descending',
};

/** The dot on the chosen item, as File Explorer marks it. */
function Dot() {
  return (
    <span className="flex w-4 shrink-0 justify-center">
      <Menu.ItemIndicator>
        <span className="block h-1.5 w-1.5 rounded-full bg-ink" />
      </Menu.ItemIndicator>
    </span>
  );
}

export function SortMenu<K extends string>({
  columns,
  value,
  onChange,
  className,
}: {
  columns: readonly SortColumn<K>[];
  value: SortState<K>;
  onChange: (next: SortState<K>) => void;
  className?: string;
}) {
  const current = columns.find((column) => column.key === value.key);
  const summary = `${current?.label ?? value.key}, ${DIRECTION_LABEL[value.order].toLowerCase()}`;

  return (
    <Menu.Root>
      <Menu.Trigger
        aria-label={`Sort: ${summary}`}
        title={`Sorted by ${summary}`}
        className={cn(buttonClasses({ variant: 'subtle', size: 'sm' }), className)}
      >
        <Icon.sortable size={16} aria-hidden className="text-accent" />
        Sort
        <Icon.caretDown size={12} aria-hidden className="text-ink-3" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Content align="start" sideOffset={4} className={MENU_CONTENT}>
          <Menu.RadioGroup
            value={value.key}
            onValueChange={(key) => {
              const column = columns.find((c) => c.key === key);
              if (column && column.key !== value.key) {
                onChange({ key: column.key, order: column.firstOrder });
              }
            }}
          >
            {columns.map((column) => (
              <Menu.RadioItem key={column.key} value={column.key} className={MENU_ITEM}>
                <Dot />
                {column.label}
              </Menu.RadioItem>
            ))}
          </Menu.RadioGroup>
          <Menu.Separator className="my-1 h-px bg-line" />
          <Menu.RadioGroup
            value={value.order}
            onValueChange={(order) => {
              if (order !== value.order) onChange({ key: value.key, order: order as SortDirection });
            }}
          >
            {(['asc', 'desc'] as const).map((order) => (
              <Menu.RadioItem key={order} value={order} className={MENU_ITEM}>
                <Dot />
                {DIRECTION_LABEL[order]}
              </Menu.RadioItem>
            ))}
          </Menu.RadioGroup>
        </Menu.Content>
      </Menu.Portal>
    </Menu.Root>
  );
}
