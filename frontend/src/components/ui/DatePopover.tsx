import { useId, useState } from 'react';

import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';
import { cn } from '@/lib/cn';

import { Button } from './Button';
import { Popover, PopoverContent, PopoverTrigger } from './Popover';

/**
 * A date chosen in place (§6.11): the trigger shows the date, the popover holds
 * a native date input — keyboard, screen-reader and locale behaviour for free —
 * and one verb to set it. Dates travel as `YYYY-MM-DD`. Limits like "not in the
 * past" are a hint here; the server is the one that checks them.
 */
export function DatePopover({
  value,
  onChange,
  label,
  verb = 'Set date',
  min,
  placeholder = 'Choose a date',
  disabled,
  className,
}: {
  value: string | null;
  onChange: (value: string) => void;
  /** Names the trigger and the input for assistive tech ("Check back on"). */
  label: string;
  verb?: string;
  min?: string;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}) {
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value ?? '');

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setDraft(value ?? '');
      }}
    >
      <PopoverTrigger
        disabled={disabled}
        aria-label={`${label}: ${value ? formatDate(value) : 'not set'}`}
        className={cn(
          'inline-flex h-9 items-center gap-2 rounded-md border border-line-strong bg-surface px-3 text-body text-ink',
          'transition-colors duration-quick hover:border-ink-3 disabled:opacity-45',
          className,
        )}
      >
        <Icon.calendar size={15} className="text-ink-3" aria-hidden />
        <span className={value ? 'tabular-nums' : 'text-ink-4'}>
          {value ? formatDate(value) : placeholder}
        </span>
      </PopoverTrigger>
      <PopoverContent className="w-64">
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (!draft) return;
            onChange(draft);
            setOpen(false);
          }}
        >
          <label className="block text-caption font-medium text-ink-2" htmlFor={inputId}>
            {label}
          </label>
          <input
            id={inputId}
            type="date"
            className="input mt-1"
            value={draft}
            min={min}
            onChange={(event) => setDraft(event.target.value)}
            autoFocus
          />
          <div className="mt-3 flex justify-end">
            <Button type="submit" size="sm" variant="primary" disabled={!draft}>
              {verb}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
