import * as DropdownMenu from '@radix-ui/react-dropdown-menu';
import { Check, ChevronDown, RotateCcw } from 'lucide-react';
import { toast } from 'sonner';

import { PERMITTED_LIFECYCLE_TRANSITIONS, STATUS_LABEL } from '../constants';
import { useTransitionExporterLifecycle } from '../hooks';
import type { ExporterLifecycleStatus } from '../types';

interface LifecycleMoveControlProps {
  customerId: string;
  currentStatus: ExporterLifecycleStatus;
}

export function lifecycleActionLabel(
  currentStatus: ExporterLifecycleStatus,
  nextStatus: ExporterLifecycleStatus,
): string {
  if (currentStatus === 'COMPLIANCE_REVIEW' && nextStatus === 'DATA_COLLECTION') {
    return 'Send back to Data Collection';
  }
  if (currentStatus === 'SUSPENDED' && nextStatus === 'ACTIVE') {
    return 'Reactivate';
  }
  return `Move to ${STATUS_LABEL[nextStatus]}`;
}

export function LifecycleMoveControl({
  customerId,
  currentStatus,
}: LifecycleMoveControlProps) {
  const mutation = useTransitionExporterLifecycle(customerId);
  const nextStates = PERMITTED_LIFECYCLE_TRANSITIONS[currentStatus];

  if (nextStates.length === 0) {
    return (
      <span className="inline-flex items-center rounded-lg border border-border bg-surface-subtle px-3 py-2 text-sm text-ink-faint">
        No further lifecycle moves
      </span>
    );
  }

  async function move(nextStatus: ExporterLifecycleStatus) {
    try {
      await mutation.mutateAsync(nextStatus);
      toast.success(`Lifecycle moved to ${STATUS_LABEL[nextStatus]}`);
    } catch {
      toast.error('Could not move lifecycle status');
    }
  }

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          disabled={mutation.isPending}
          className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-ink shadow-sm hover:bg-surface-subtle disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Move exporter to another lifecycle status"
        >
          {mutation.isPending ? 'Moving…' : 'Move to…'}
          <ChevronDown size={15} />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={6}
          className="z-50 min-w-64 rounded-lg border border-border bg-surface p-1 shadow-lg"
        >
          <DropdownMenu.Label className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Legal next states
          </DropdownMenu.Label>
          {nextStates.map((nextStatus) => {
            const isSendBack =
              currentStatus === 'COMPLIANCE_REVIEW' && nextStatus === 'DATA_COLLECTION';
            return (
              <DropdownMenu.Item
                key={nextStatus}
                disabled={mutation.isPending}
                onSelect={() => void move(nextStatus)}
                className="flex cursor-pointer items-start gap-2 rounded-md px-3 py-2 text-sm text-ink outline-none hover:bg-surface-subtle focus:bg-surface-subtle data-[disabled]:cursor-not-allowed data-[disabled]:opacity-50"
              >
                {isSendBack ? (
                  <RotateCcw size={15} className="mt-0.5 shrink-0 text-status-review" />
                ) : (
                  <Check size={15} className="mt-0.5 shrink-0 text-brand-600" />
                )}
                <span>
                  <span className="block font-medium">{lifecycleActionLabel(currentStatus, nextStatus)}</span>
                  {isSendBack && (
                    <span className="mt-0.5 block text-xs text-ink-faint">
                      Compliance rejection / more data required
                    </span>
                  )}
                </span>
              </DropdownMenu.Item>
            );
          })}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  );
}
