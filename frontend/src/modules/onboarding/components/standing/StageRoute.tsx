/**
 * A deal's stage as a route (frontend-plan §8.6): Open ── Gathering paperwork ──
 * Handed over, with the deal's place marked. A withdrawn deal shows the route it left
 * and says so. Drawing only — moves are the server's `allowed_stage_moves`, offered
 * as buttons elsewhere.
 */

import { cn } from '@/lib/cn';

import type { DealStage } from '../../types';

const ROUTE: { stage: DealStage; label: string }[] = [
  { stage: 'OPEN', label: 'Open' },
  { stage: 'GATHERING_PAPERWORK', label: 'Gathering paperwork' },
  { stage: 'HANDED_OVER', label: 'Handed over' },
];

export function StageRoute({ stage, compact = false }: { stage: DealStage; compact?: boolean }) {
  const withdrawn = stage === 'WITHDRAWN';
  const at = ROUTE.findIndex((step) => step.stage === stage);
  return (
    <span
      className={cn('inline-flex flex-wrap items-center gap-y-1', compact ? 'text-caption' : 'text-secondary')}
      data-testid="stage-route"
      data-stage={stage}
    >
      {ROUTE.map((step, index) => {
        const reached = !withdrawn && index <= at;
        const current = index === at;
        return (
          <span key={step.stage} className="inline-flex items-center">
            {index > 0 && (
              <span
                aria-hidden
                className={cn('mx-1.5 h-px', compact ? 'w-3' : 'w-6', reached ? 'bg-ink' : 'bg-line-strong')}
              />
            )}
            <span
              className={cn(
                'inline-flex items-center gap-1.5 whitespace-nowrap',
                current ? 'font-semibold text-ink' : reached ? 'text-ink-2' : 'text-ink-3',
                withdrawn && 'line-through decoration-ink-4',
              )}
              aria-current={current ? 'step' : undefined}
            >
              <span
                aria-hidden
                className={cn(
                  'h-2 w-2 rounded-full border',
                  reached ? 'border-ink bg-ink' : 'border-ink-3 bg-transparent',
                  current && 'ring-2 ring-ink/20',
                )}
              />
              {compact && !current ? null : step.label}
            </span>
          </span>
        );
      })}
      {withdrawn && (
        <span className="ml-3 rounded-sm bg-idle-tint px-1.5 py-0.5 text-caption font-medium text-ink-2">Withdrawn</span>
      )}
    </span>
  );
}
