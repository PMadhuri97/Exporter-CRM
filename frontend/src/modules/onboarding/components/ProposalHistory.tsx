/**
 * How a company's background-check proposals ended — **owner: Developer 1** (maker-
 * checker, plan P3-1c).
 *
 * The open proposal is shown by `AwaitingApproval`; this lists the resolved ones, newest
 * first, so the maker sees who approved, who rejected and why, or that it was withdrawn.
 * An approved proposal's decision is also in the decision trail, with both names; a
 * rejected or withdrawn one leaves no decision, so this is where it shows. Served by
 * `GET …/background-check/proposals`; nothing is derived here. Renders nothing until
 * something has been resolved.
 */

import { formatDateTime } from '@/lib/format';

import { useBackgroundCheckProposals } from '../hooks';
import type { BackgroundCheckProposal } from '../types';

import { actorLabel } from './actor-label';
import { proposedMoveLabel } from './background-check-labels';

const SHOWN = 5;

const OUTCOME: Record<string, { verb: string; tone: string }> = {
  APPROVED: { verb: 'Approved', tone: 'text-emerald-700' },
  REJECTED: { verb: 'Rejected', tone: 'text-red-700' },
  WITHDRAWN: { verb: 'Withdrawn', tone: 'text-slate-600' },
};

function Resolved({ proposal }: { proposal: BackgroundCheckProposal }) {
  const outcome = OUTCOME[proposal.status] ?? { verb: proposal.status, tone: 'text-slate-600' };
  return (
    <li data-testid="resolved-proposal" data-status={proposal.status} className="text-xs text-slate-600">
      <span className="font-medium text-slate-900">{proposedMoveLabel(proposal.to_value)}</span>
      {' proposed by '}
      {actorLabel(proposal.proposed_by_name, proposal.proposed_by)}, {formatDateTime(proposal.proposed_at)}
      {' — '}
      <span className={`font-medium ${outcome.tone}`}>{outcome.verb}</span>
      {proposal.resolved_by && ` by ${actorLabel(proposal.resolved_by_name, proposal.resolved_by)}`}
      {proposal.resolved_at && `, ${formatDateTime(proposal.resolved_at)}`}
      {proposal.resolution_reason && `: ${proposal.resolution_reason}`}
    </li>
  );
}

export function ProposalHistory({ customerId }: { customerId: string }) {
  const query = useBackgroundCheckProposals(customerId);
  if (query.isLoading) return null;
  if (query.isError) {
    return (
      <p role="alert" className="text-xs text-red-700">
        The proposals could not be loaded.
      </p>
    );
  }
  const resolved = (query.data?.proposals ?? []).filter((p) => p.status !== 'OPEN');
  if (resolved.length === 0) return null;
  return (
    <div data-testid="proposal-history">
      <h4 className="text-sm font-semibold text-slate-900">Proposals</h4>
      <ul className="mt-2 flex flex-col gap-1.5">
        {resolved.slice(0, SHOWN).map((proposal) => (
          <Resolved key={proposal.id} proposal={proposal} />
        ))}
      </ul>
    </div>
  );
}
