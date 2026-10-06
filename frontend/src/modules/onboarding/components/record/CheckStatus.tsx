/**
 * The background check's status and its moves (frontend-plan §8.5.1): the current
 * state as a worded badge, then **only the moves the server listed in
 * `allowed_moves`**, as buttons — no state map, nothing drawn that cannot be done. A
 * move that needs a second officer reads "Propose …". An open proposal shows an
 * "Awaiting approval" badge with the proposer and the time, and the approver's slot
 * waiting. The decision itself is recorded by the existing decision form, opened on
 * the chosen move.
 */

import { Badge, Button } from '@/components';
import { formatDateTime } from '@/lib/format';

import type { BackgroundCheckMove, BackgroundCheckProposal, BackgroundCheckState } from '../../types';
import { actorLabel } from '../actor-label';

import { BACKGROUND_CHECK_STATUS, MEANING_TONE } from './status';

/** The order moves are offered in: the order the states are read in. */
const ORDER: BackgroundCheckState[] = ['NOT_STARTED', 'IN_REVIEW', 'MORE_INFO', 'CLEAR', 'FLAGGED', 'ON_HOLD'];

function Signatures({ proposal }: { proposal: BackgroundCheckProposal }) {
  const target = BACKGROUND_CHECK_STATUS[proposal.to_value].label;
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-secondary" data-testid="proposal-signatures">
      <Badge variant="outline">Awaiting approval</Badge>
      <span className="text-ink">
        {target} · Proposed by {actorLabel(proposal.proposed_by_name, proposal.proposed_by)},{' '}
        {formatDateTime(proposal.proposed_at)}
      </span>
      <span className="text-ink-3">Waiting for a second compliance officer</span>
    </div>
  );
}

export function CheckStatus({
  value,
  moves,
  openProposal,
  onChoose,
  showStatus = true,
}: {
  value: BackgroundCheckState;
  /** Exactly what the server served. */
  moves: BackgroundCheckMove[];
  openProposal?: BackgroundCheckProposal | null;
  /** Opens the decision form on the chosen move; absent, nothing is a button. */
  onChoose?: (to: BackgroundCheckState) => void;
  /** Off where the status is already drawn above (the Background check tab). */
  showStatus?: boolean;
}) {
  const look = BACKGROUND_CHECK_STATUS[value];
  const offered = onChoose
    ? ORDER.map((state) => moves.find((move) => move.to_value === state && state !== value)).filter(
        (move): move is BackgroundCheckMove => move !== undefined,
      )
    : [];

  return (
    <div className="space-y-3" data-testid="check-status">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {showStatus && (
          <div className="flex items-center gap-2" aria-current="step">
            <span className="text-caption text-ink-3">Status</span>
            <Badge tone={MEANING_TONE[look.meaning]}>{look.label}</Badge>
          </div>
        )}
        {offered.length > 0 && (
          <div className="flex flex-wrap items-center gap-2">
            {offered.map((move) => {
              const label = BACKGROUND_CHECK_STATUS[move.to_value].label;
              return (
                <Button
                  key={move.to_value}
                  size="sm"
                  onClick={() => onChoose?.(move.to_value)}
                  data-check-move={move.to_value}
                >
                  {move.approval_required ? `Propose ${label}` : label}
                </Button>
              );
            })}
          </div>
        )}
      </div>
      {openProposal && <Signatures proposal={openProposal} />}
    </div>
  );
}
