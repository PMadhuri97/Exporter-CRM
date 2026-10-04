/**
 * The background check as a state map (frontend-plan §6.3):
 *
 *   Not started ─▶ In review ◀──▶ More info
 *                      │
 *            Clear     Flagged ──▶ On hold
 *
 * The current node is solid and ringed. **Only the moves the server listed in
 * `allowed_moves` are buttons** — every other node is drawn but inert, so the map
 * shows what is possible without suggesting what is not. A move that needs a second
 * officer reads "Propose …". An open proposal draws its target dashed, with two
 * signature slots: the proposer's (signed) and the approver's (waiting). The decision
 * itself is recorded by the existing decision form, opened on the chosen move.
 */

import type { ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';

import type { BackgroundCheckMove, BackgroundCheckProposal, BackgroundCheckState } from '../../types';
import { actorLabel } from '../actor-label';

import { Lamp } from './Lamp';
import { BACKGROUND_CHECK_LAMP, MEANING_TEXT } from './lamps';

function Node({
  value,
  current,
  move,
  proposed,
  onChoose,
}: {
  value: BackgroundCheckState;
  current: boolean;
  move: BackgroundCheckMove | undefined;
  proposed: boolean;
  onChoose?: (to: BackgroundCheckState) => void;
}) {
  const look = BACKGROUND_CHECK_LAMP[value];
  const face = (
    <>
      <Lamp shape={look.shape} meaning={look.meaning} size={14} awaitingApproval={proposed} />
      <span className="whitespace-nowrap">
        {move?.approval_required ? `Propose ${look.label}` : look.label}
      </span>
    </>
  );
  const base = 'inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-secondary';
  if (move && onChoose) {
    return (
      <button
        type="button"
        onClick={() => onChoose(value)}
        className={cn(
          base,
          'border border-dashed border-line-strong font-medium text-ink transition-colors duration-quick hover:border-ink hover:bg-sunken',
        )}
        data-runway-move={value}
      >
        {face}
      </button>
    );
  }
  return (
    <span
      className={cn(
        base,
        current && cn('bg-surface font-semibold ring-1 ring-ink', MEANING_TEXT[look.meaning]),
        !current && proposed && 'border border-dashed border-ink text-ink',
        !current && !proposed && 'text-ink-3',
      )}
      aria-current={current ? 'step' : undefined}
    >
      {face}
    </span>
  );
}

function Arrow({ children = '→' }: { children?: ReactNode }) {
  return (
    <span aria-hidden className="px-1 text-ink-4">
      {children}
    </span>
  );
}

function Signatures({ proposal }: { proposal: BackgroundCheckProposal }) {
  return (
    <div className="mt-3 flex flex-wrap items-center gap-x-5 gap-y-1 text-secondary" data-testid="runway-signatures">
      <span className="inline-flex items-center gap-1.5 text-ink">
        <Icon.signature size={15} aria-hidden />
        Proposed by {actorLabel(proposal.proposed_by_name, proposal.proposed_by)}, {formatDateTime(proposal.proposed_at)}
        <Icon.check size={13} className="text-positive" aria-hidden />
        <span className="sr-only">(signed)</span>
      </span>
      <span className="inline-flex items-center gap-1.5 text-ink-3">
        <span aria-hidden className="h-3 w-3 rounded-full border border-dashed border-ink-3" />
        Waiting for a second compliance officer
      </span>
    </div>
  );
}

export function CheckRunway({
  value,
  moves,
  openProposal,
  onChoose,
}: {
  value: BackgroundCheckState;
  /** Exactly what the server served. */
  moves: BackgroundCheckMove[];
  openProposal?: BackgroundCheckProposal | null;
  /** Opens the decision form on the chosen move; absent, nothing is a button. */
  onChoose?: (to: BackgroundCheckState) => void;
}) {
  const moveTo = (to: BackgroundCheckState) => moves.find((move) => move.to_value === to);
  const node = (state: BackgroundCheckState) => (
    <Node
      value={state}
      current={value === state}
      move={state === value ? undefined : moveTo(state)}
      proposed={openProposal?.to_value === state}
      onChoose={onChoose}
    />
  );

  return (
    <div data-testid="check-runway">
      <ol aria-label="Background check" className="space-y-2">
        <li className="flex flex-wrap items-center gap-y-2">
          {node('NOT_STARTED')}
          <Arrow />
          {node('IN_REVIEW')}
          <Arrow>⇄</Arrow>
          {node('MORE_INFO')}
        </li>
        <li className="flex flex-wrap items-center gap-y-2 pl-6">
          <Arrow>↳</Arrow>
          {node('CLEAR')}
          <span className="w-3" />
          {node('FLAGGED')}
          <Arrow />
          {node('ON_HOLD')}
        </li>
      </ol>
      {openProposal && <Signatures proposal={openProposal} />}
    </div>
  );
}
