/**
 * Qualification.
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

import {
  Button,
  EmptyLine,
  Input,
  Panel,
  Segmented,
  Skeleton,
  Tag,
  Textarea,
  type TagTone,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { QualificationChip } from '../../components';
import { QUALIFICATION_LABEL, RESULT_LABEL } from '../../constants';
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

const RESULT_TONE: Record<CriterionResultValue, TagTone> = {
  PASS: 'positive',
  FAIL: 'negative',
  UNKNOWN: 'idle',
};

interface ResultDraft {
  result: CriterionResultValue | '';
  observed_value: string;
  evidence_note: string;
}

const EMPTY_DRAFT: ResultDraft = { result: '', observed_value: '', evidence_note: '' };

/** "≥ USD 100,000,000", "optional" — what the criterion asks, from its own fields. */
function asks(criterion: Qualification['standings'][number]['criterion']): string | null {
  const parts: string[] = [];
  if (criterion.threshold !== null && criterion.threshold !== undefined) {
    const sign = criterion.comparison === 'AT_LEAST' ? '≥' : criterion.comparison === 'AT_MOST' ? '≤' : '';
    parts.push([sign, criterion.unit, String(criterion.threshold)].filter(Boolean).join(' '));
  }
  if (!criterion.required) parts.push('optional');
  return parts.length > 0 ? parts.join(' · ') : null;
}

/**
 * The scorecard (frontend-plan §8.5): one row per criterion with what it asks, its
 * latest result and — where the server allows recording (`can_record_results`) — a
 * Pass / Fail / Unknown choice with the observed value and an evidence note. Choosing
 * nothing leaves a criterion as it is. Changed rows collect into one sticky "Record N
 * results" bar; nothing is sent per keystroke, and earlier results stay on the record.
 */
function Scorecard({
  customerId,
  qualification,
}: {
  customerId: string;
  qualification: Qualification;
}) {
  const mutation = useRecordQualificationResults(customerId);
  const canRecord = qualification.can_record_results;
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

  const rows = (
    <ul className="divide-y divide-line">
      {qualification.standings.map(({ criterion, latest_result, counts }) => {
        const draft = drafts[criterion.key] ?? EMPTY_DRAFT;
        const ask = asks(criterion);
        return (
          <li key={criterion.key} className="py-3" data-testid="scorecard-row">
            <div className="grid gap-x-6 gap-y-2 md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto] md:items-center">
              <div className="min-w-0">
                <p className="text-body font-medium text-ink">{criterion.label}</p>
                {ask && <p className="text-caption text-ink-3">{ask}</p>}
              </div>
              <div className="flex flex-wrap items-center gap-2 text-secondary text-ink-2">
                {latest_result ? (
                  <>
                    <Tag tone={RESULT_TONE[latest_result.result]}>{RESULT_LABEL[latest_result.result]}</Tag>
                    {latest_result.observed_value && <span>observed {latest_result.observed_value}</span>}
                    <span className="text-ink-3">{formatDate(latest_result.recorded_at)}</span>
                    {!counts && <span className="text-ink-3">(earlier version)</span>}
                  </>
                ) : (
                  <span className="text-ink-3">Not recorded</span>
                )}
              </div>
              {canRecord && (
                <Segmented
                  label={`${criterion.label} result`}
                  size="sm"
                  value={draft.result}
                  onValueChange={(result) => update(criterion.key, { result })}
                  onClear={() => update(criterion.key, { result: '' })}
                  options={RESULT_VALUES.map((value) => ({ value, label: RESULT_LABEL[value] }))}
                />
              )}
            </div>
            {canRecord && draft.result !== '' && (
              <div className="mt-2 grid gap-2 md:grid-cols-2">
                <Input
                  aria-label={`${criterion.label} observed value`}
                  placeholder={criterion.unit ? `Observed (${criterion.unit})` : 'Observed value'}
                  value={draft.observed_value}
                  onChange={(e) => update(criterion.key, { observed_value: e.target.value })}
                />
                <Input
                  aria-label={`${criterion.label} evidence`}
                  placeholder="Evidence note — what this rests on"
                  value={draft.evidence_note}
                  onChange={(e) => update(criterion.key, { evidence_note: e.target.value })}
                />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );

  if (!canRecord) return rows;

  return (
    <form
      aria-label="Record results"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {rows}
      {entries.length > 0 && (
        <div className="sticky bottom-0 z-10 -mx-1 mt-3 flex items-center justify-between gap-3 rounded border border-line bg-raised px-4 py-2.5 shadow-float">
          <span className="text-secondary text-ink-2">
            {entries.length} {entries.length === 1 ? 'result' : 'results'} to record. Earlier results stay on the record.
          </span>
          <div className="flex gap-2">
            <Button variant="subtle" size="sm" onClick={() => setDrafts({})}>
              Discard
            </Button>
            <Button type="submit" variant="primary" size="sm" loading={mutation.isPending}>
              Record {entries.length} {entries.length === 1 ? 'result' : 'results'}
            </Button>
          </div>
        </div>
      )}
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
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <span className="mr-1 text-body text-ink-2">Decide:</span>
        {allowed.map((value) => (
          <Button
            key={value}
            size="sm"
            variant={value === 'QUALIFIED' ? 'primary' : 'secondary'}
            onClick={() => setOutcome(value)}
          >
            Record: {QUALIFICATION_LABEL[value]}
          </Button>
        ))}
      </div>
    );
  }

  // Reasons are asked for only on NOT_QUALIFIED, where at least one is required. The
  // server allows them on QUALIFIED too (`criterion-result.md`), but every seeded code
  // is a reason to reject, so offering them there would only invite a contradiction.
  const available =
    outcome === 'NOT_QUALIFIED'
      ? (reasonCodes.data?.reason_codes ?? []).filter((code) => code.active)
      : [];

  return (
    <form
      aria-label="Record outcome"
      className="mt-5 space-y-3 border-t border-line pt-4"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate(
          {
            outcome,
            reason_codes: outcome === 'NOT_QUALIFIED' ? codes : [],
            note: note.trim() || null,
          },
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
      <h3 className="text-body font-semibold text-ink">Record: {QUALIFICATION_LABEL[outcome]}</h3>
      {outcome === 'QUALIFIED' && (
        <p className="text-caption text-ink-2">
          Qualifying a lead makes it a prospect. The decision is final.
        </p>
      )}
      {available.length > 0 && (
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-caption font-medium text-ink-3">
            Reasons
          </legend>
          {available.map((code) => (
            <label key={code.code} className="flex items-center gap-2 text-body text-ink">
              <input
                type="checkbox"
                className="h-4 w-4 accent-ink"
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
      <Textarea
        aria-label="Note"
        className="min-h-[4rem]"
        placeholder="Note"
        value={note}
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="flex justify-end gap-2">
        <Button variant="subtle" size="sm" onClick={reset}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={mutation.isPending}>
          Confirm
        </Button>
      </div>
    </form>
  );
}

export function QualificationPanel({ customerId }: { customerId: string }) {
  const { data, isLoading, isError } = useQualification(customerId);
  const allowedOutcomes = data?.allowed_outcomes ?? [];

  return (
    <Panel
      aria-label="Qualification"
      title="Qualification"
      description="Criteria are set by an administrator. The suggestion is not the decision — a person decides."
      actions={
        data && (
          <div className="flex items-center gap-2 text-body text-ink-2">
            <QualificationChip state={data.state} />
            {data.state === 'NOT_YET_REVIEWED' && (
              <span data-testid="qualification-suggestion" className="inline-flex items-center gap-1">
                <Icon.hint size={14} className="text-attention" />
                Suggested: {QUALIFICATION_LABEL[data.suggested_outcome]}
              </span>
            )}
          </div>
        )
      }
    >
      {isLoading && <Skeleton className="h-24" />}
      {isError && <p className="text-body text-negative">Couldn't load qualification.</p>}

      {data && (
        <>
          {data.standings.length === 0 ? (
            <EmptyLine>No qualification criteria are set up yet.</EmptyLine>
          ) : (
            <Scorecard customerId={customerId} qualification={data} />
          )}

          {data.outcomes.length > 0 && (
            <div className="mt-5">
              <h3 className="text-caption font-medium text-ink-3">
                Decisions
              </h3>
              <ol className="mt-2 space-y-2 border-l border-line pl-4 text-body">
                {data.outcomes.map((outcome) => (
                  <li key={outcome.id} className="relative text-ink">
                    <span
                      aria-hidden
                      className="absolute -left-[1.3rem] top-1.5 h-2 w-2 rounded-full bg-line-strong"
                    />
                    <span className="font-medium">{QUALIFICATION_LABEL[outcome.outcome]}</span>
                    <span className="text-ink-2">
                      {' · '}
                      {formatDate(outcome.decided_at)}
                      {outcome.outcome !== outcome.suggested_outcome &&
                        ` · suggestion was ${QUALIFICATION_LABEL[outcome.suggested_outcome]}`}
                      {outcome.reason_codes.length > 0 && ` · ${outcome.reason_codes.join(', ')}`}
                      {outcome.note && ` · ${outcome.note}`}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          )}

          {allowedOutcomes.length > 0 && (
            <OutcomeForm customerId={customerId} allowed={allowedOutcomes} />
          )}
        </>
      )}
    </Panel>
  );
}
