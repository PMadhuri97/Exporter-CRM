import type { ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

export interface PathStep<K extends string = string> {
  key: K;
  label: string;
}

/**
 * Chevron steps, as in Salesforce Path and the Dynamics business process flow
 * (frontend-plan §6.5). Completed steps are a blue tint with a check, the current
 * step solid blue, upcoming steps grey. One guidance line sits beside it.
 *
 * Read-only unless the caller passes `selectable`: the keys of the steps the
 * server lists as moves. Only those become buttons; clicking one selects it (the
 * caller then offers *Mark as current*). The path never offers a move on its own.
 */
export function Path<K extends string>({
  steps,
  current,
  label,
  selectable,
  selected,
  onSelect,
  guidance,
  className,
}: {
  steps: readonly PathStep<K>[];
  /** The current step. A key not in `steps` (or null) leaves every step upcoming. */
  current: K | null;
  /** The path's accessible name: "Journey", "Conversation", "Deal stage". */
  label: string;
  /** The steps that may be chosen — exactly the moves the server served. */
  selectable?: readonly K[];
  /** The step chosen but not yet marked as current. */
  selected?: K | null;
  onSelect?: (key: K) => void;
  /** One line beside the path: what moves the current stage on. */
  guidance?: ReactNode;
  className?: string;
}) {
  const at = steps.findIndex((step) => step.key === current);
  return (
    <div className={cn('flex flex-wrap items-center gap-x-4 gap-y-2', className)}>
      <ol aria-label={label} className="flex min-w-0 flex-1 items-stretch">
        {steps.map((step, index) => {
          const state = at === -1 || index > at ? 'upcoming' : index < at ? 'completed' : 'current';
          const choosable = selectable?.includes(step.key) && onSelect !== undefined;
          const chosen = selected === step.key;
          const first = index === 0;
          const last = index === steps.length - 1;
          const look = cn(
            'relative flex h-8 min-w-0 flex-1 items-center justify-center gap-1.5 px-4 text-secondary',
            // The chevron: a notch on the left (but the first), a point on the right
            // (but the last). Drawn by clip-path, so the step stays one element.
            first ? 'rounded-l pl-3' : '[--notch:10px]',
            last ? 'rounded-r pr-3' : '[--point:10px]',
            '[clip-path:polygon(0_0,calc(100%-var(--point,0px))_0,100%_50%,calc(100%-var(--point,0px))_100%,0_100%,var(--notch,0px)_50%)]',
            !first && '-ml-1.5',
            state === 'completed' && 'bg-accent-tint text-accent',
            state === 'current' && 'bg-accent-solid font-semibold text-white',
            state === 'upcoming' && 'bg-sunken text-ink-2',
            chosen && 'bg-accent-solid-hover font-semibold text-white',
          );
          const content = (
            <>
              {state === 'completed' && !chosen && <Icon.check size={14} className="shrink-0" aria-hidden />}
              <span className="truncate">{step.label}</span>
              {state === 'completed' && <span className="sr-only">, done</span>}
              {state === 'current' && <span className="sr-only">, current</span>}
            </>
          );
          return (
            <li
              key={step.key}
              className="flex min-w-0 flex-1"
              aria-current={state === 'current' ? 'step' : undefined}
            >
              {choosable ? (
                <button
                  type="button"
                  aria-pressed={chosen}
                  onClick={() => onSelect(step.key)}
                  // The chevron's clip would cut an outer focus ring, so this one is inset.
                  className={cn(
                    look,
                    'transition-colors duration-quick hover:brightness-95',
                    'focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ink focus-visible:ring-offset-0',
                  )}
                >
                  {content}
                </button>
              ) : (
                <span className={look}>{content}</span>
              )}
            </li>
          );
        })}
      </ol>
      {guidance && <p className="text-secondary text-ink-2">{guidance}</p>}
    </div>
  );
}
