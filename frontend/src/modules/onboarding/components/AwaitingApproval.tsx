/**
 * The "Awaiting approval" state of the background check (maker-checker).
 *
 * A proposed CLEAR, FLAGGED or ON_HOLD, served as `open_proposal` on the background-
 * check read. The gauge has not moved; nothing else moves it until a second compliance
 * officer approves or rejects the proposal, or its proposer withdraws it. The buttons
 * are exactly the server's `allowed_actions` for this user — the proposer never sees
 * Approve. An out-of-date proposal (the check or its inputs moved since) says why and
 * can only be rejected or withdrawn.
 */

import { useState } from 'react';

import { formatDateTime } from '@/lib/format';

import type { BackgroundCheckProposal, BackgroundCheckProposalAction } from '../types';

import { actorLabel } from './actor-label';
import { proposedMoveLabel } from './background-check-labels';
import { ProposalResolveDialog } from './ProposalResolveDialog';
import { RiskChip } from './RiskChip';

const BUTTONS: Record<BackgroundCheckProposalAction, { label: string; primary: boolean }> = {
  APPROVE: { label: 'Approve', primary: true },
  REJECT: { label: 'Reject', primary: false },
  WITHDRAW: { label: 'Withdraw', primary: false },
};

export function AwaitingApproval({ proposal }: { proposal: BackgroundCheckProposal }) {
  const [action, setAction] = useState<BackgroundCheckProposalAction | null>(null);
  const actions = proposal.allowed_actions ?? [];

  return (
    <div
      data-testid="awaiting-approval"
      className="mt-3 rounded-md border border-dashed border-ink/60 p-3"
    >
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium text-ink">Awaiting approval:</span>
        <span className="font-medium text-ink">
          {proposedMoveLabel(proposal.to_value)}
        </span>
        {proposal.risk_rating && <RiskChip risk={proposal.risk_rating} />}
      </div>
      <p className="mt-1 text-xs text-ink-2">
        Proposed by {actorLabel(proposal.proposed_by_name, proposal.proposed_by)},{' '}
        {formatDateTime(proposal.proposed_at)} — {proposal.reason}
      </p>
      {proposal.stale_reason && (
        <p data-testid="proposal-stale" className="mt-2 rounded bg-attention-tint p-2 text-xs text-attention">
          This proposal is out of date ({proposal.stale_reason}). It can no longer be
          approved: reject or withdraw it, and record the decision again.
        </p>
      )}
      {actions.length === 0 && (
        <p className="mt-2 text-xs text-ink-3">
          A second compliance officer must approve or reject it.
        </p>
      )}
      {action === null ? (
        actions.length > 0 && (
          <div className="mt-3 flex gap-2">
            {actions.map((candidate) => (
              <button
                key={candidate}
                type="button"
                onClick={() => setAction(candidate)}
                className={
                  BUTTONS[candidate].primary
                    ? 'rounded bg-ink px-3 py-1.5 text-sm text-paper'
                    : 'rounded border border-line-strong bg-surface px-3 py-1.5 text-sm'
                }
              >
                {BUTTONS[candidate].label}
              </button>
            ))}
          </div>
        )
      ) : (
        <div className="mt-3">
          <ProposalResolveDialog
            proposal={proposal}
            action={action}
            onDone={() => setAction(null)}
            onCancel={() => setAction(null)}
          />
        </div>
      )}
    </div>
  );
}
