/**
 * Approve, reject or withdraw a proposed background-check decision (maker-checker).
 *
 * The second click of "approve from Home in two clicks": the first opens this, with
 * what was proposed, by whom, when and why; the second confirms. Rejecting needs a
 * reason; withdrawing (the proposer's own) may have one.
 *
 * Which of the three is offered comes from the server (`allowed_actions`): the proposer
 * sees Withdraw, another compliance officer Approve and Reject, and an out-of-date
 * proposal only Reject. The server checks again under its lock, so a 409 here (someone
 * resolved it first, or the inputs moved) is shown as its message and the screens
 * reload.
 */

import { useState } from 'react';

import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

import { useResolveBackgroundCheckProposal } from '../hooks';
import type { BackgroundCheckProposal, BackgroundCheckProposalAction } from '../types';

import { actorLabel } from './actor-label';
import { proposedMoveLabel } from './background-check-labels';
import { RiskChip } from './RiskChip';

const TITLES: Record<BackgroundCheckProposalAction, string> = {
  APPROVE: 'Approve this decision',
  REJECT: 'Reject this decision',
  WITHDRAW: 'Withdraw your proposal',
};

const CONFIRM: Record<BackgroundCheckProposalAction, string> = {
  APPROVE: 'Approve',
  REJECT: 'Reject',
  WITHDRAW: 'Withdraw',
};

const PENDING: Record<BackgroundCheckProposalAction, string> = {
  APPROVE: 'Approving…',
  REJECT: 'Rejecting…',
  WITHDRAW: 'Withdrawing…',
};

export function ProposalResolveDialog({
  proposal,
  action,
  onDone,
  onCancel,
}: {
  proposal: BackgroundCheckProposal;
  action: BackgroundCheckProposalAction;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [reason, setReason] = useState('');
  const resolve = useResolveBackgroundCheckProposal(proposal.company_id);
  const reasonRequired = action === 'REJECT';
  const canSubmit = !reasonRequired || reason.trim().length > 0;

  const submit = () => {
    const text = reason.trim();
    const resolution =
      action === 'APPROVE'
        ? ({ kind: 'APPROVE' } as const)
        : action === 'REJECT'
          ? ({ kind: 'REJECT', reason: text } as const)
          : ({ kind: 'WITHDRAW', reason: text || null } as const);
    resolve.mutate({ proposalId: proposal.id, resolution }, { onSuccess: onDone });
  };

  return (
    <div
      role="dialog"
      aria-label={TITLES[action]}
      data-testid="proposal-resolve-dialog"
      className="rounded-lg border border-line bg-surface p-4"
    >
      <h4 className="text-sm font-semibold text-ink">{TITLES[action]}</h4>
      <dl className="mt-2 space-y-1 text-sm text-ink-2">
        {proposal.company_name && (
          <div>
            <dt className="inline text-ink-3">Company: </dt>
            <dd className="inline">{proposal.company_name}</dd>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <dt className="text-ink-3">Proposed:</dt>
          <dd className="font-medium">{proposedMoveLabel(proposal.to_value)}</dd>
          {proposal.risk_rating && <RiskChip risk={proposal.risk_rating} />}
        </div>
        <div>
          <dt className="inline text-ink-3">By: </dt>
          <dd className="inline">
            {actorLabel(proposal.proposed_by_name, proposal.proposed_by)},{' '}
            {formatDateTime(proposal.proposed_at)}
          </dd>
        </div>
        <div>
          <dt className="inline text-ink-3">Reason: </dt>
          <dd className="inline">{proposal.reason}</dd>
        </div>
        <div className="text-xs text-ink-3">
          Rests on {proposal.evidence_count} item{proposal.evidence_count === 1 ? '' : 's'}
          {proposal.cycle_number ? ` in cycle ${proposal.cycle_number}` : ''}.
        </div>
      </dl>

      {action === 'APPROVE' && (
        <p className="mt-3 rounded bg-sunken p-2 text-xs text-ink-2">
          Approving records the decision now — decided by{' '}
          {actorLabel(proposal.proposed_by_name, proposal.proposed_by)}, approved by you
          {proposal.to_value === 'CLEAR' && '; a qualified prospect becomes a customer'}.
        </p>
      )}

      {action !== 'APPROVE' && (
        <label className="mt-3 block text-sm">
          <span className="text-xs font-medium text-ink-2">
            {reasonRequired ? 'Reason (required)' : 'Reason (optional)'}
          </span>
          <textarea
            aria-label="Reason"
            rows={3}
            className="mt-1 w-full rounded border border-line-strong p-2 text-sm"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>
      )}

      {resolve.isError && (
        <p role="alert" className="mt-3 text-xs text-negative">
          {resolve.error instanceof ApiError
            ? resolve.error.message
            : 'The proposal could not be updated.'}
        </p>
      )}

      <div className="mt-4 flex gap-2">
        <button
          type="button"
          disabled={!canSubmit || resolve.isPending}
          onClick={submit}
          className="rounded bg-ink px-3 py-1.5 text-sm text-paper disabled:opacity-40"
        >
          {resolve.isPending ? PENDING[action] : CONFIRM[action]}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border border-line-strong px-3 py-1.5 text-sm"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}
