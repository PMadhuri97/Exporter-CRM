/**
 * Qualification — **owner: Developer 2** (L2-09, L2-10, L2-14).
 *
 * Shows where each criterion stands, the server's suggestion and the decisions
 * people have recorded, and lets a permitted user record results and an
 * outcome. What the user may do is served, not derived: the results form
 * appears only when `can_record_results` is true, and the outcome buttons are
 * exactly `allowed_outcomes`. Reason codes come from the server too. Every
 * rule the server enforces (evidence for PASS/FAIL, reason codes for
 * NOT_QUALIFIED, a note for codes that need one) is enforced there; a refusal
 * is shown as the server worded it.
 *
 * The suggestion is not the decision. A QUALIFIED decision moves a lead to
 * prospect on the server; this panel never moves the journey itself.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { formatDate } from '@/lib/format';

import { QualificationChip } from '../../components';
import { QUALIFICATION_LABEL, RESULT_CLASSES, RESULT_LABEL } from '../../constants';
import {
  useQualification,
  useReasonCodes,
  useRecordQualificationOutcome,
  useRecordQualificationResults,
} from '../../hooks';
import type {
  CriterionResultValue,
  Qualification,
  QualificationOutcomeValue,
  RecordResultsRequest,
} from '../../types';

const RESULT_VALUES: CriterionResultValue[] = ['PASS', 'FAIL', 'UNKNOWN'];

interface ResultDraft {
  result: CriterionResultValue | '';
  observed_value: string;
  evidence_note: string;
}

const EMPTY_DRAFT: ResultDraft = { result: '', observed_value: '', evidence_note: '' };

function ResultsForm({
  customerId,
  qualification,
}: {
  customerId: string;
  qualification: Qualification;
}) {
  const mutation = useRecordQualificationResults(customerId);
  const [drafts, setDrafts] = useState<Record<string, ResultDraft>>({});

  const update = (key: string, patch: Partial<ResultDraft>) =>
    setDrafts((current) => ({
      ...current,
      [key]: { ...EMPTY_DRAFT, ...current[key], ...patch },
    }));

  const entries = Object.entries(drafts).filter(([, draft]) => draft.result !== '');

  const submit = () => {
    const request: RecordResultsRequest = {
      results: entries.map(([key, draft]) => ({
        criterion_key: key,
        result: draft.result as CriterionResultValue,
        observed_value: draft.observed_value.trim() || null,
        evidence_note: draft.evidence_note.trim() || null,
      })),
    };
    mutation.mutate(request, {
      onSuccess: () => {
        toast.success('Results recorded');
        setDrafts({});
      },
      onError: (error) => toast.error(error.message),
    });
  };

  return (
    <form
      aria-label="Record results"
      className="mt-4 space-y-3 border-t border-border pt-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <h3 className="text-sm font-semibold text-ink">Record results</h3>
      {qualification.standings.map(({ criterion }) => {
        const draft = drafts[criterion.key] ?? EMPTY_DRAFT;
        return (
          <div key={criterion.key} className="grid gap-2 md:grid-cols-[1fr_8rem_1fr_1.5fr]">
            <span className="self-center text-sm text-ink">{criterion.label}</span>
            <select
              aria-label={`${criterion.label} result`}
              className="input"
              value={draft.result}
              onChange={(e) =>
                update(criterion.key, { result: e.target.value as CriterionResultValue | '' })
              }
            >
              <option value="">No change</option>
              {RESULT_VALUES.map((value) => (
                <option key={value} value={value}>
                  {RESULT_LABEL[value]}
                </option>
              ))}
            </select>
            <input
              aria-label={`${criterion.label} observed value`}
              className="input"
              placeholder={criterion.unit ? `Observed (${criterion.unit})` : 'Observed value'}
              value={draft.observed_value}
              onChange={(e) => update(criterion.key, { observed_value: e.target.value })}
            />
            <input
              aria-label={`${criterion.label} evidence`}
              className="input"
              placeholder="Evidence note"
              value={draft.evidence_note}
              onChange={(e) => update(criterion.key, { evidence_note: e.target.value })}
            />
          </div>
        );
      })}
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={entries.length === 0 || mutation.isPending}
          className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Save results
        </button>
      </div>
    </form>
  );
}

function OutcomeForm({
  customerId,
  allowed,
}: {
  customerId: string;
  allowed: QualificationOutcomeValue[];
}) {
  const mutation = useRecordQualificationOutcome(customerId);
  const reasonCodes = useReasonCodes();
  const [outcome, setOutcome] = useState<QualificationOutcomeValue | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [note, setNote] = useState('');

  const reset = () => {
    setOutcome(null);
    setCodes([]);
    setNote('');
  };

  if (!outcome) {
    return (
      <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
        {allowed.map((value) => (
          <button
            key={value}
            type="button"
            onClick={() => setOutcome(value)}
            className="rounded-lg border border-border px-3 py-1.5 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Record: {QUALIFICATION_LABEL[value]}
          </button>
        ))}
      </div>
    );
  }

  const available = (reasonCodes.data?.reason_codes ?? []).filter((code) => code.active);

  return (
    <form
      aria-label="Record outcome"
      className="mt-4 space-y-3 border-t border-border pt-4"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate(
          { outcome, reason_codes: codes, note: note.trim() || null },
          {
            onSuccess: () => {
              toast.success(`Recorded: ${QUALIFICATION_LABEL[outcome]}`);
              reset();
            },
            onError: (error) => toast.error(error.message),
          },
        );
      }}
    >
      <h3 className="text-sm font-semibold text-ink">Record: {QUALIFICATION_LABEL[outcome]}</h3>
      {available.length > 0 && (
        <fieldset className="space-y-1">
          <legend className="text-xs font-medium uppercase tracking-wide text-ink-faint">
            Reasons
          </legend>
          {available.map((code) => (
            <label key={code.code} className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                checked={codes.includes(code.code)}
                onChange={(e) =>
                  setCodes((current) =>
                    e.target.checked
                      ? [...current, code.code]
                      : current.filter((c) => c !== code.code),
                  )
                }
              />
              {code.label}
            </label>
          ))}
        </fieldset>
      )}
      <textarea
        aria-label="Note"
        className="input min-h-[4rem] w-full"
        placeholder="Note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={reset}
          className="rounded-lg px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-sunken"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={mutation.isPending}
          className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Confirm
        </button>
      </div>
    </form>
  );
}

export function QualificationPanel({ customerId }: { customerId: string }) {
  const { data, isLoading, isError } = useQualification(customerId);
  const allowedOutcomes = data?.allowed_outcomes ?? [];

  return (
    <section
      aria-label="Qualification"
      className="rounded-lg border border-border bg-surface p-5 shadow-card"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="font-semibold text-ink">Qualification</h2>
        {data && (
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <QualificationChip state={data.state} />
            {data.state === 'NOT_YET_REVIEWED' && (
              <span data-testid="qualification-suggestion">
                Suggested: {QUALIFICATION_LABEL[data.suggested_outcome]}
              </span>
            )}
          </div>
        )}
      </div>

      {isLoading && <div className="mt-3 h-24 animate-pulse rounded bg-surface-sunken" />}
      {isError && <p className="mt-3 text-sm text-status-failed">Couldn't load qualification.</p>}

      {data && (
        <>
          {data.standings.length === 0 ? (
            <p className="mt-3 text-sm text-ink-muted">No qualification criteria are set up yet.</p>
          ) : (
            <table className="mt-3 w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
                  <th className="py-2 font-medium">Criterion</th>
                  <th className="py-2 font-medium">Result</th>
                  <th className="py-2 font-medium">Observed</th>
                  <th className="py-2 font-medium">Recorded</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.standings.map(({ criterion, latest_result, counts }) => (
                  <tr key={criterion.key}>
                    <td className="py-2 text-ink">
                      {criterion.label}
                      {criterion.required && (
                        <span className="ml-1 text-xs text-ink-faint">(required)</span>
                      )}
                    </td>
                    <td className="py-2">
                      {latest_result ? (
                        <span className={RESULT_CLASSES[latest_result.result]}>
                          {RESULT_LABEL[latest_result.result]}
                          {!counts && (
                            <span className="ml-1 text-xs text-ink-faint">(earlier version)</span>
                          )}
                        </span>
                      ) : (
                        <span className="text-ink-faint">Not recorded</span>
                      )}
                    </td>
                    <td className="py-2 text-ink-muted">{latest_result?.observed_value ?? '—'}</td>
                    <td className="py-2 text-ink-muted">
                      {latest_result ? formatDate(latest_result.recorded_at) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {data.outcomes.length > 0 && (
            <div className="mt-4">
              <h3 className="text-xs font-medium uppercase tracking-wide text-ink-faint">
                Decisions
              </h3>
              <ul className="mt-1 space-y-1 text-sm">
                {data.outcomes.map((outcome) => (
                  <li key={outcome.id} className="text-ink">
                    {QUALIFICATION_LABEL[outcome.outcome]}
                    <span className="text-ink-muted">
                      {' · '}
                      {formatDate(outcome.decided_at)}
                      {outcome.outcome !== outcome.suggested_outcome &&
                        ` · suggestion was ${QUALIFICATION_LABEL[outcome.suggested_outcome]}`}
                      {outcome.reason_codes.length > 0 && ` · ${outcome.reason_codes.join(', ')}`}
                      {outcome.note && ` · ${outcome.note}`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.can_record_results && data.standings.length > 0 && (
            <ResultsForm customerId={customerId} qualification={data} />
          )}
          {allowedOutcomes.length > 0 && (
            <OutcomeForm customerId={customerId} allowed={allowedOutcomes} />
          )}
        </>
      )}
    </section>
  );
}
