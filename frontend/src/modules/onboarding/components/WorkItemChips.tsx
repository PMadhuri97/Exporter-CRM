/**
 * The small facts a compliance work row carries: how long it has waited, whether it is
 * due soon or overdue (in business time, worked out by the server), a high-risk Clear
 * that needs a senior approver, and how many times it came back.
 *
 * Never an identifier and never a reason: a row is a name, a stage and times.
 */

import { Tag } from '@/components';
import { Icon } from '@/design/icons';
import { formatDateTime } from '@/lib/format';

import type { ComplianceWorkItem } from '../types';

export function DueChip({
  dueAt,
  isOverdue,
  isDueSoon,
}: {
  dueAt: string | null | undefined;
  isOverdue: boolean;
  isDueSoon: boolean;
}) {
  if (!dueAt) return null;
  if (isOverdue) {
    return (
      <Tag tone="negative" title={`Was due ${formatDateTime(dueAt)}`}>
        Overdue
      </Tag>
    );
  }
  if (isDueSoon) {
    return (
      <Tag tone="attention" title={`Due ${formatDateTime(dueAt)}`}>
        Due soon
      </Tag>
    );
  }
  return null;
}

export function WorkItemChips({ item }: { item: ComplianceWorkItem }) {
  return (
    <>
      <DueChip dueAt={item.due_at} isOverdue={item.is_overdue} isDueSoon={item.is_due_soon} />
      {item.needs_senior_approval && (
        <Tag tone="attention" icon={<Icon.warning size={11} aria-hidden />}>
          Senior approval
        </Tag>
      )}
      {item.rejection_count > 0 && <Tag tone="idle">Returned ×{item.rejection_count}</Tag>}
      {item.reviewer_inactive && <Tag tone="negative">Reviewer deactivated</Tag>}
      {item.stage === 'approval' && item.eligible_checker_count === 0 && (
        <Tag tone="negative">No one can approve</Tag>
      )}
    </>
  );
}
