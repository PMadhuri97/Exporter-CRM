import * as ToggleGroup from '@radix-ui/react-toggle-group';
import type { ReactNode } from 'react';

import { cn } from '@/lib/cn';

export interface SegmentedOption<T extends string> {
  value: T;
  label: ReactNode;
  /** A count after the label ("Leads 48"); a capped count is passed as text ("200+"). */
  count?: ReactNode;
  disabled?: boolean;
}

/**
 * One choice out of a few, side by side in one outlined group (§6.15) — a filter
 * lens, a criterion's Pass / Fail / Unknown. Always exactly one value: clicking
 * the chosen segment again keeps it chosen (unless `onClear` is given). Arrow keys move
 * between segments.
 */
export function Segmented<T extends string>({
  value,
  onValueChange,
  options,
  label,
  size = 'md',
  onClear,
  className,
}: {
  /** `''` is "nothing chosen", possible only with `onClear`. */
  value: T | '';
  onValueChange: (value: T) => void;
  options: readonly SegmentedOption<T>[];
  /** The group's accessible name. */
  label: string;
  size?: 'sm' | 'md';
  /** Given, choosing the chosen segment again clears it — "no change" on a scorecard row. */
  onClear?: () => void;
  className?: string;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      value={value}
      onValueChange={(next) => {
        if (next) onValueChange(next as T);
        else onClear?.();
      }}
      aria-label={label}
      className={cn(
        'inline-flex flex-wrap items-center gap-0.5 rounded border border-line-strong bg-surface p-0.5',
        className,
      )}
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          disabled={option.disabled}
          className={cn(
            'inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm text-ink-2 transition-colors duration-quick',
            'hover:bg-sunken hover:text-ink disabled:pointer-events-none disabled:opacity-45',
            'data-[state=on]:bg-accent-tint data-[state=on]:font-semibold data-[state=on]:text-accent',
            size === 'sm' ? 'h-6 px-2 text-caption' : 'h-7 px-2.5 text-secondary',
          )}
        >
          {option.label}
          {option.count !== undefined && (
            <span className="tabular-nums text-ink-3">{option.count}</span>
          )}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}
