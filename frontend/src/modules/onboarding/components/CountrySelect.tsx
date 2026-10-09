/**
 * Choose a country by name; the CRM stores its ISO code.
 *
 * A button that looks like the other selects, opening a searchable list: type "ind" and
 * India and Indonesia are offered. India is pinned first. The value in and out is always
 * the two-letter code (or '' for none), so forms and the server keep working in codes
 * while people work in names. A stored value that is not a known code is still shown,
 * as itself, so editing an old record never hides what it holds.
 */

import { Command } from 'cmdk';
import { useMemo, useState } from 'react';

import { Popover, PopoverContent, PopoverTrigger } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

import { countryLabel, countryOptions, PINNED_COUNTRY } from '../countries';

const ITEM =
  'flex h-8 cursor-default select-none items-center gap-2 rounded px-2.5 text-body text-ink outline-none data-[selected=true]:bg-sunken';

export interface CountrySelectProps {
  id?: string;
  /** The ISO code, or '' for none. */
  value: string;
  onChange: (code: string) => void;
  disabled?: boolean;
  /** Marks the control invalid (a field error is shown by the surrounding `Field`). */
  invalid?: boolean;
  placeholder?: string;
  className?: string;
  'aria-describedby'?: string;
}

export function CountrySelect({
  id,
  value,
  onChange,
  disabled,
  invalid,
  placeholder = 'Choose a country',
  className,
  'aria-describedby': describedBy,
}: CountrySelectProps) {
  const [open, setOpen] = useState(false);
  const options = useMemo(() => countryOptions(), []);
  const label = countryLabel(value);

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          role="combobox"
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-invalid={invalid || undefined}
          aria-describedby={describedBy}
          disabled={disabled}
          className={cn(
            'input flex items-center justify-between gap-2 text-left',
            invalid && 'border-negative',
            className,
          )}
        >
          <span className={cn('min-w-0 truncate', !label && 'text-ink-4')}>{label || placeholder}</span>
          <Icon.caretDown size={14} className="shrink-0 text-ink-3" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent className="w-[--radix-popover-trigger-width] min-w-[16rem] p-1">
        <Command
          label="Countries"
          filter={(itemValue, search) =>
            itemValue.toLowerCase().includes(search.trim().toLowerCase()) ? 1 : 0
          }
        >
          <div className="flex h-8 items-center gap-2 border-b border-line px-2.5">
            <Icon.search size={14} className="shrink-0 text-ink-3" aria-hidden />
            <Command.Input
              autoFocus
              placeholder="Search countries"
              className="h-full min-w-0 flex-1 bg-transparent text-body text-ink outline-none placeholder:text-ink-3 focus-visible:ring-0 focus-visible:ring-offset-0"
            />
          </div>
          <Command.List className="max-h-64 overflow-y-auto py-1">
            <Command.Empty className="px-2.5 py-2 text-secondary text-ink-3">No country matches.</Command.Empty>
            {options.map((option) => (
              <Command.Item
                key={option.code}
                // Searchable by name and by code: "india", "ind", "in".
                value={`${option.name} ${option.code}`}
                onSelect={() => {
                  onChange(option.code);
                  setOpen(false);
                }}
                className={cn(ITEM, option.code === PINNED_COUNTRY && 'font-semibold')}
              >
                <span className="min-w-0 flex-1 truncate">{option.name}</span>
                <span className="shrink-0 text-secondary text-ink-3">{option.code}</span>
                {option.code === value.toUpperCase() && (
                  <Icon.check size={14} className="shrink-0 text-accent" aria-label="Selected" />
                )}
              </Command.Item>
            ))}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
