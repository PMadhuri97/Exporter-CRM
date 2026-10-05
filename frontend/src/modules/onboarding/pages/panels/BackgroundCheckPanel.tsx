/**
 * The background check: the gauge, with `VerificationSection` rendered below it.
 *
 * The gauge answers "is it safe and lawful to work with this company?" (architecture
 * §3.3). The verification results and the eight-item screening checklist below it are
 * the **inputs** to that answer, not the answer — which is why they are two sections
 * and not one, and why this panel does not summarise them.
 *
 * **The server decides what may happen next.** `allowed_moves` comes from the API for
 * the signed-in user, and the dialog offers exactly those. This file holds no move
 * table and no role list: a rule change on the server cannot leave a stale button here.
 *
 * Every move is sent with the value the panel was showing (`from_value`). If someone
 * moved the check in the meantime the server refuses it with a 409 instead of turning
 * it into a different act, and the panel reloads so the person decides again on what
 * is actually there.
 *
 * The one role check that remains is the one the page already applied: DEVELOPER may
 * read the CRM but the background-check routes refuse it (settled 28 September
 * 2026), so the panel is not rendered for it rather than rendered broken.
 *
 * Since 1 October 2026 the panel names the current check cycle and, when the
 * server offers them (`allowed_cycle_actions`), the Re-KYC / Re-KYB buttons;
 * a Clear's expiry is shown; each decision opens to the evidence it rested on
 * and decisions are grouped by cycle.
 *
 * Maker-checker: a proposed CLEAR, FLAGGED or ON_HOLD
 * shows as "Awaiting approval" with exactly the actions the server allows this user
 * (approve / reject for a second officer, withdraw for the proposer); the required
 * checks and their state in the current cycle; a "Re-KYC due" badge when the
 * Clear has expired or soon will; the proposals already resolved — approved,
 * rejected with the reason, or withdrawn — so the maker sees how theirs ended.
 */

import { useState } from 'react';

import { Button, Card, FormPanel } from '@/components';
import { ApiError } from '@/lib/api/errors';
import { formatDate } from '@/lib/format';

import {
  BackgroundCheckGauge,
  BackgroundCheckMoveDialog,
  CheckStatus,
  DecisionHistory,
  RiskChip,
  VerificationSection,
} from '../../components';
import {
  cycleKindLabel,
  describeClearBlocker,
} from '../../components/background-check-labels';
import { AwaitingApproval } from '../../components/AwaitingApproval';
import { CheckCycleActions } from '../../components/CheckCycleActions';
import { RequiredChecks } from '../../components/ComplianceCheckChip';
import { ProposalHistory } from '../../components/ProposalHistory';
import {
  useBackgroundCheck,
  useBackgroundCheckDecisions,
  useRecordBackgroundCheckDecision,
} from '../../hooks';
import type { BackgroundCheckState } from '../../types';

function GaugeSection({ customerId }: { customerId: string }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  // The move chosen in the status card, opened already selected (frontend-plan §8.5.1).
  const [initialMove, setInitialMove] = useState<BackgroundCheckState | null>(null);
  const check = useBackgroundCheck(customerId);
  const decisions = useBackgroundCheckDecisions(customerId);
  const record = useRecordBackgroundCheckDecision(customerId);

  if (check.isLoading) {
    return (
      <section aria-busy className="space-y-2">
        <p className="text-body text-ink-3">Loading the background check…</p>
      </section>
    );
  }

  if (check.isError || !check.data) {
    return (
      <section>
        <h3 className="text-heading font-semibold text-ink">Background check</h3>
        <p role="alert" className="mt-2 text-body text-negative">
          The background check could not be loaded.
        </p>
      </section>
    );
  }

  const standing = check.data;
  const moves = standing.allowed_moves ?? [];
  const blocked = standing.clear_blocked_reasons ?? [];
  const cycle = standing.current_cycle ?? null;
  const compliance = standing.compliance;

  return (
    <section>
      <Card as="h3" title="Background check">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <BackgroundCheckGauge
              value={standing.value}
              awaitingApproval={standing.awaiting_approval}
              rekycDue={standing.rekyc_due}
            />
          </div>
          {cycle && (
            <p data-testid="current-cycle" className="mt-2 text-caption text-ink-2">
              Cycle {cycle.number} · {cycleKindLabel(cycle.kind)} · started{' '}
              {formatDate(cycle.started_at)}
              {cycle.reason && ` — ${cycle.reason}`}
            </p>
          )}
          {compliance?.is_clear && compliance.clear_expires_at && (
            <p
              data-testid="clear-expiry"
              className={`mt-1 text-caption ${compliance.is_clear_current ? 'text-ink-2' : 'font-medium text-negative'}`}
            >
              {compliance.is_clear_current
                ? `Clear until ${formatDate(compliance.clear_expires_at)}`
                : `Clear expired on ${formatDate(compliance.clear_expires_at)} — Re-KYC due`}
            </p>
          )}
        </div>
        {moves.length > 0 && !dialogOpen && (
          <Button
            size="sm"
            onClick={() => {
              setInitialMove(null);
              setDialogOpen(true);
            }}
          >
            Record a decision
          </Button>
        )}
      </div>

      {/* Only the served moves, as buttons; and an open proposal, if there is one. */}
      <div className="mt-4 border-t border-line pt-4">
        <CheckStatus
          value={standing.value}
          moves={moves}
          openProposal={standing.open_proposal}
          showStatus={false}
          onChoose={(to) => {
            setInitialMove(to);
            setDialogOpen(true);
          }}
        />
      </div>

      {standing.risk_rating && (
        <div className="mt-3 flex items-center gap-2">
          <span className="text-caption text-ink-3">Risk</span>
          <RiskChip risk={standing.risk_rating} />
          {standing.value !== 'CLEAR' && (
            // The risk is the last one anyone recorded, not a statement about the
            // company now — the reader's caveat, said plainly rather than hidden.
            <span className="text-caption text-ink-3">
              from the most recent decision that set one
            </span>
          )}
        </div>
      )}

      {standing.open_proposal && <AwaitingApproval proposal={standing.open_proposal} />}

      {standing.value === 'IN_REVIEW' && (
        <RequiredChecks checks={standing.required_checks ?? []} />
      )}

      {!dialogOpen && (
        <CheckCycleActions
          customerId={customerId}
          actions={standing.allowed_cycle_actions ?? []}
        />
      )}

      {standing.value === 'IN_REVIEW' && blocked.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t border-line pt-3">
          <span className="text-caption text-ink-3">Still needed</span>
          <p className="min-w-0 flex-1 text-secondary text-ink-2">
            Before this company can be cleared: {blocked.map(describeClearBlocker).join('; ')}.
          </p>
        </div>
      )}
      </Card>

      {dialogOpen && (
        <FormPanel title="Record a decision" onClose={() => setDialogOpen(false)}>
          <BackgroundCheckMoveDialog
            initialMove={initialMove}
            moves={moves}
            blockedReasons={blocked}
            isPending={record.isPending}
            error={
              record.isError
                ? record.error instanceof ApiError
                  ? record.error.message
                  : 'The decision could not be recorded.'
                : null
            }
            onSubmit={(body) =>
              record.mutate(
                { ...body, from_value: standing.value },
                { onSuccess: () => setDialogOpen(false) },
              )
            }
            onCancel={() => setDialogOpen(false)}
          />
        </FormPanel>
      )}

      <div className="mt-4 empty:hidden">
        <ProposalHistory customerId={customerId} />
      </div>

      <Card as="h3" title="Decisions" className="mt-4">
        <DecisionHistory
          decisions={decisions.data?.decisions ?? []}
          isLoading={decisions.isLoading}
          isError={decisions.isError}
          customerId={customerId}
        />
      </Card>
    </section>
  );
}

export function BackgroundCheckPanel({
  customerId,
  isStaff,
}: {
  customerId: string;
  isStaff: boolean;
}) {
  if (!isStaff) return null;
  return (
    <div className="flex flex-col gap-4">
      <GaugeSection customerId={customerId} />
      {/* The verification section, rendered below the gauge: the checks are the
          inputs to the decision, so they read in that order. */}
      <VerificationSection customerId={customerId} />
    </div>
  );
}
