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

import { Lightbulb } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  Chip,
  EmptySection,
  Input,
  Panel,
  Select,
  Skeleton,
  Table,
  TBody,
  Td,
  Textarea,
  Th,
  THead,
  Tr,
  type ChipTone,
} from '@/components';
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

const RESULT_TONE: Record<CriterionResultValue, ChipTone> = {
  PASS: 'success',
  FAIL: 'danger',
  UNKNOWN: 'neutral',
};

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
      className="mt-5 space-y-3 border-t border-border pt-4"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div>
        <h3 className="text-sm font-semibold text-ink">Record results</h3>
        <p className="text-xs text-ink-muted">
          Only the criteria you set are sent. Earlier results stay on the record.
        </p>
      </div>
      {qualification.standings.map(({ criterion }) => {
        const draft = drafts[criterion.key] ?? EMPTY_DRAFT;
        return (
          <div key={criterion.key} className="grid gap-2 md:grid-cols-[1fr_8rem_1fr_1.5fr]">
            <span className="self-center text-sm text-ink">{criterion.label}</span>
            <Select
              aria-label={`${criterion.label} result`}
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
            </Select>
            <Input
              aria-label={`${criterion.label} observed value`}
              placeholder={criterion.unit ? `Observed (${criterion.unit})` : 'Observed value'}
              value={draft.observed_value}
              onChange={(e) => update(criterion.key, { observed_value: e.target.value })}
            />
            <Input
              aria-label={`${criterion.label} evidence`}
              placeholder="Evidence note"
              value={draft.evidence_note}
              onChange={(e) => update(criterion.key, { evidence_note: e.target.value })}
            />
          </div>
        );
      })}
      <div className="flex justify-end">
        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={entries.length === 0}
          loading={mutation.isPending}
        >
          Save results
        </Button>
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
      <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-4">
        <span className="mr-1 text-sm text-ink-muted">Decide:</span>
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

  const available = (reasonCodes.data?.reason_codes ?? []).filter((code) => code.active);

  return (
    <form
      aria-label="Record outcome"
      className="mt-5 space-y-3 border-t border-border pt-4"
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
      {outcome === 'QUALIFIED' && (
        <p className="text-xs text-ink-muted">
          Qualifying a lead makes it a prospect. The decision is final.
        </p>
      )}
      {available.length > 0 && (
        <fieldset className="space-y-1.5">
          <legend className="mb-1 text-xs font-medium uppercase tracking-wide text-ink-faint">
            Reasons
          </legend>
          {available.map((code) => (
            <label key={code.code} className="flex items-center gap-2 text-sm text-ink">
              <input
                type="checkbox"
                className="h-4 w-4 accent-brand-600"
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
        <Button variant="ghost" size="sm" onClick={reset}>
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
          <div className="flex items-center gap-2 text-sm text-ink-muted">
            <QualificationChip state={data.state} />
            {data.state === 'NOT_YET_REVIEWED' && (
              <span data-testid="qualification-suggestion" className="inline-flex items-center gap-1">
                <Lightbulb size={14} className="text-status-review" />
                Suggested: {QUALIFICATION_LABEL[data.suggested_outcome]}
              </span>
            )}
          </div>
        )
      }
    >
      {isLoading && <Skeleton className="h-24" />}
      {isError && <p className="text-sm text-status-failed">Couldn't load qualification.</p>}

      {data && (
        <>
          {data.standings.length === 0 ? (
            <EmptySection>No qualification criteria are set up yet.</EmptySection>
          ) : (
            <div className="-mx-5">
              <Table className="min-w-[32rem]">
                <THead>
                  <tr>
                    <Th>Criterion</Th>
                    <Th>Result</Th>
                    <Th>Observed</Th>
                    <Th>Recorded</Th>
                  </tr>
                </THead>
                <TBody>
                  {data.standings.map(({ criterion, latest_result, counts }) => (
                    <Tr key={criterion.key}>
                      <Td className="text-ink">
                        {criterion.label}
                        {criterion.required && (
                          <span className="ml-1 text-xs text-ink-faint">(required)</span>
                        )}
                      </Td>
                      <Td>
                        {latest_result ? (
                          <span className="inline-flex items-center gap-1.5">
                            <Chip tone={RESULT_TONE[latest_result.result]}>
                              {RESULT_LABEL[latest_result.result]}
                            </Chip>
                            {!counts && (
                              <span className="text-xs text-ink-faint">(earlier version)</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-ink-faint">Not recorded</span>
                        )}
                      </Td>
                      <Td className="text-ink-muted">{latest_result?.observed_value ?? '—'}</Td>
                      <Td className="text-ink-muted">
                        {latest_result ? formatDate(latest_result.recorded_at) : '—'}
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            </div>
          )}

          {data.outcomes.length > 0 && (
            <div className="mt-5">
              <h3 className="text-xs font-medium uppercase tracking-wide text-ink-faint">
                Decisions
              </h3>
              <ol className="mt-2 space-y-2 border-l border-border pl-4 text-sm">
                {data.outcomes.map((outcome) => (
                  <li key={outcome.id} className="relative text-ink">
                    <span
                      aria-hidden
                      className="absolute -left-[1.3rem] top-1.5 h-2 w-2 rounded-full bg-border-strong"
                    />
                    <span className="font-medium">{QUALIFICATION_LABEL[outcome.outcome]}</span>
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
              </ol>
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
    </Panel>
  );
}
