/**
 * The background check — **owner: Developer 4A** for the gauge (L4-03, L4-08, L4-13);
 * **Developer 4B** for `VerificationSection`, which is rendered below and untouched.
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
 * The one role check that remains is the one the page already applied: DEVELOPER may
 * read the CRM but the background-check routes refuse it (D8 is unanswered and the
 * default is no widening), so the panel is not rendered for it rather than rendered
 * broken.
 */

import { useState } from 'react';

import {
  BackgroundCheckGauge,
  BackgroundCheckMoveDialog,
  DecisionHistory,
  RiskChip,
  VerificationSection,
} from '../../components';
import {
  useBackgroundCheck,
  useBackgroundCheckDecisions,
  useRecordBackgroundCheckDecision,
} from '../../hooks';

function GaugeSection({ customerId }: { customerId: string }) {
  const [dialogOpen, setDialogOpen] = useState(false);
  const check = useBackgroundCheck(customerId);
  const decisions = useBackgroundCheckDecisions(customerId);
  const record = useRecordBackgroundCheckDecision(customerId);

  if (check.isLoading) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <p className="text-sm text-slate-500">Loading the background check…</p>
      </section>
    );
  }

  if (check.isError || !check.data) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-4">
        <h3 className="text-base font-semibold text-slate-900">Background check</h3>
        <p role="alert" className="mt-2 text-sm text-red-700">
          The background check could not be loaded.
        </p>
      </section>
    );
  }

  const standing = check.data;
  const moves = standing.allowed_moves ?? [];
  const blocked = standing.clear_blocked_reasons ?? [];

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-base font-semibold text-slate-900">Background check</h3>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <BackgroundCheckGauge value={standing.value} />
          </div>
        </div>
        {moves.length > 0 && !dialogOpen && (
          <button
            type="button"
            onClick={() => setDialogOpen(true)}
            className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
          >
            Record a decision
          </button>
        )}
      </div>

      {standing.risk_rating && (
        <div className="mt-3 flex items-center gap-2">
          <RiskChip risk={standing.risk_rating} />
          {standing.value !== 'CLEAR' && (
            // The risk is the last one anyone recorded, not a statement about the
            // company now — the reader's D6 caveat, said plainly rather than hidden.
            <span className="text-xs text-slate-500">
              from the most recent decision that set one
            </span>
          )}
        </div>
      )}

      {standing.value === 'IN_REVIEW' && blocked.length > 0 && (
        <p className="mt-3 rounded bg-slate-50 p-2 text-xs text-slate-600">
          Before this company can be cleared: {blocked.join(', ')}.
        </p>
      )}

      {dialogOpen && (
        <div className="mt-4">
          <BackgroundCheckMoveDialog
            moves={moves}
            blockedReasons={blocked}
            isPending={record.isPending}
            error={record.isError ? 'The decision could not be recorded.' : null}
            onSubmit={(body) =>
              record.mutate(body, { onSuccess: () => setDialogOpen(false) })
            }
            onCancel={() => setDialogOpen(false)}
          />
        </div>
      )}

      <div className="mt-5">
        <h4 className="text-sm font-semibold text-slate-900">Decisions</h4>
        <div className="mt-2">
          <DecisionHistory
            decisions={decisions.data?.decisions ?? []}
            isLoading={decisions.isLoading}
            isError={decisions.isError}
          />
        </div>
      </div>
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
      {/* Developer 4B's, unchanged and rendered below the gauge: the checks are the
          inputs to the decision, so they read in that order. */}
      <VerificationSection customerId={customerId} />
    </div>
  );
}
