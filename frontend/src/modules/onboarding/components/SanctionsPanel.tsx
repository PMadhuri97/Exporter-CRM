/**
 * Sanctions screening on the Background check tab.
 *
 * * **Coverage.** Every subject — the company, each beneficial owner on record, anyone
 *   else screened — with its latest screening in this check cycle: when, against which
 *   lists (and their version dates), and the outcome. A subject never screened, or due a
 *   re-screen (a newer list version, a name change), is highlighted with why.
 * * **The flag.** A proposed or confirmed true match flags the company; its deals
 *   cannot be handed over while it stands.
 * * **Record a screening** (compliance): the lists come ticked from Settings — the
 *   mandatory ones cannot be unticked — and each possible match is entered with a
 *   first decision and why.
 * * **Decide a match** on the latest screening: false positive, true match, escalate or
 *   reopen, always with a reason. A true match waits for a second officer, who
 *   confirms or rejects it here or on Compliance work.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Badge,
  Button,
  Card,
  EmptyLine,
  Field,
  FormPanel,
  Input,
  RequiredNote,
  Select,
  Skeleton,
  Textarea,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate, formatDateTime } from '@/lib/format';

import {
  useCompanySanctions,
  useRecordSanctionsRun,
  useSanctionsHitAction,
  useSanctionsLists,
} from '../hooks';
import type {
  RecordSanctionsRunRequest,
  SanctionsDisposition,
  SanctionsHit,
  SanctionsHitRequest,
  SanctionsRun,
  SanctionsSubject,
} from '../types';

import {
  DISPOSITION_LABEL,
  DISPOSITION_TONE,
  OUTCOME_LABEL,
  OUTCOME_TONE,
  SUBJECT_LABEL,
  type SanctionsOutcome,
} from './sanctions-labels';

type Decision = Exclude<SanctionsDisposition, 'TRUE_MATCH_PROPOSED'>;
const DECISIONS: Decision[] = ['OPEN', 'FALSE_POSITIVE', 'TRUE_MATCH', 'ESCALATED'];

const EMPTY_HIT: SanctionsHitRequest = {
  list_code: '',
  matched_name: '',
  list_entry_id: null,
  score: null,
  disposition: 'OPEN',
  reason: null,
};

function RecordForm({
  customerId,
  subject,
  ubos,
  onDone,
}: {
  customerId: string;
  /** The subject to screen; absent for "the company". */
  subject?: SanctionsSubject;
  ubos: SanctionsSubject[];
  onDone: () => void;
}) {
  const lists = useSanctionsLists();
  const record = useRecordSanctionsRun(customerId);
  const active = (lists.data?.lists ?? []).filter((list) => list.active);
  const [subjectType, setSubjectType] = useState<SanctionsSubject['subject_type']>(subject?.subject_type ?? 'COMPANY');
  const [uboId, setUboId] = useState(subject?.subject_reference ?? '');
  const [director, setDirector] = useState(subject?.subject_type === 'DIRECTOR' ? subject.subject_name : '');
  const [chosen, setChosen] = useState<Set<string> | null>(null);
  const [hits, setHits] = useState<SanctionsHitRequest[]>([]);
  const [note, setNote] = useState('');
  // Until the person touches the boxes, every active list is ticked.
  const ticked = chosen ?? new Set(active.map((list) => list.code));
  const hitsReady = hits.every(
    (hit) => hit.list_code && hit.matched_name.trim() && (hit.disposition === 'OPEN' || (hit.reason ?? '').trim()),
  );
  const subjectReady =
    subjectType === 'COMPANY' || (subjectType === 'UBO' ? Boolean(uboId) : Boolean(director.trim()));
  const ready = ticked.size > 0 && hitsReady && subjectReady;

  const setHit = (index: number, change: Partial<SanctionsHitRequest>) =>
    setHits((prev) => prev.map((hit, i) => (i === index ? { ...hit, ...change } : hit)));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const body: RecordSanctionsRunRequest = {
      subject_type: subjectType,
      subject_name: subjectType === 'DIRECTOR' ? director.trim() : null,
      subject_reference: subjectType === 'UBO' ? uboId : null,
      list_codes: [...ticked],
      aliases: [],
      country: null,
      provider: 'MANUAL',
      provider_reference: null,
      note: note.trim() || null,
      hits: hits.map((hit) => ({
        ...hit,
        matched_name: hit.matched_name.trim(),
        reason: (hit.reason ?? '').trim() || null,
      })),
    };
    try {
      const run = await record.mutateAsync(body);
      toast.success(`Screening recorded: ${OUTCOME_LABEL[run.outcome as SanctionsOutcome]}`);
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not record the screening');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <Field label="Who was screened" htmlFor="sanctions-subject" required>
        <Select
          id="sanctions-subject"
          value={subjectType}
          onChange={(event) => setSubjectType(event.target.value as SanctionsSubject['subject_type'])}
        >
          <option value="COMPANY">The company</option>
          {ubos.length > 0 && <option value="UBO">A beneficial owner</option>}
          <option value="DIRECTOR">A director</option>
        </Select>
      </Field>
      {subjectType === 'UBO' && (
        <Field label="Beneficial owner" htmlFor="sanctions-ubo" required>
          <Select id="sanctions-ubo" value={uboId} onChange={(event) => setUboId(event.target.value)}>
            <option value="">Choose</option>
            {ubos.map((ubo) => (
              <option key={ubo.subject_reference} value={ubo.subject_reference ?? ''}>
                {ubo.subject_name}
              </option>
            ))}
          </Select>
        </Field>
      )}
      {subjectType === 'DIRECTOR' && (
        <Field label="Director's name" htmlFor="sanctions-director" required>
          <Input id="sanctions-director" value={director} onChange={(e) => setDirector(e.target.value)} />
        </Field>
      )}
      <fieldset className="space-y-1.5">
        <legend className="text-caption font-medium text-ink-2">Lists screened</legend>
        {lists.isLoading && <Skeleton className="h-10" />}
        {active.map((list) => (
          <label key={list.code} className="flex items-center gap-2 text-body text-ink-2">
            <input
              type="checkbox"
              checked={ticked.has(list.code)}
              disabled={list.mandatory}
              onChange={(event) => {
                const next = new Set(ticked);
                if (event.target.checked) next.add(list.code);
                else next.delete(list.code);
                setChosen(next);
              }}
              className="h-4 w-4 rounded border-line-strong accent-accent-solid"
            />
            {list.name}
            <span className="text-caption text-ink-3">
              version {formatDate(list.list_version_date)}
              {list.mandatory ? ' · mandatory' : ''}
            </span>
          </label>
        ))}
      </fieldset>

      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <p className="text-caption font-medium text-ink-2">Possible matches</p>
          <Button size="sm" variant="subtle" onClick={() => setHits((prev) => [...prev, { ...EMPTY_HIT }])}>
            <Icon.add size={14} /> Add a match
          </Button>
        </div>
        {hits.length === 0 && <EmptyLine className="py-0">No possible matches — the screening is clean.</EmptyLine>}
        {hits.map((hit, index) => (
          <div key={index} className="space-y-2 rounded-lg border border-line p-3" data-testid="sanctions-hit-input">
            <div className="grid gap-2 sm:grid-cols-2">
              <Field label="List" htmlFor={`hit-list-${index}`} required>
                <Select id={`hit-list-${index}`} value={hit.list_code} onChange={(e) => setHit(index, { list_code: e.target.value })}>
                  <option value="">Choose</option>
                  {active
                    .filter((list) => ticked.has(list.code))
                    .map((list) => (
                      <option key={list.code} value={list.code}>
                        {list.name}
                      </option>
                    ))}
                </Select>
              </Field>
              <Field label="Name on the list" htmlFor={`hit-name-${index}`} required>
                <Input id={`hit-name-${index}`} value={hit.matched_name} onChange={(e) => setHit(index, { matched_name: e.target.value })} />
              </Field>
              <Field label="List entry ID" htmlFor={`hit-entry-${index}`}>
                <Input
                  id={`hit-entry-${index}`}
                  value={hit.list_entry_id ?? ''}
                  onChange={(e) => setHit(index, { list_entry_id: e.target.value || null })}
                />
              </Field>
              <Field label="Match score (0–100)" htmlFor={`hit-score-${index}`}>
                <Input
                  id={`hit-score-${index}`}
                  type="number"
                  min={0}
                  max={100}
                  value={hit.score ?? ''}
                  onChange={(e) => setHit(index, { score: e.target.value === '' ? null : e.target.value })}
                />
              </Field>
              <Field label="Decision" htmlFor={`hit-decision-${index}`}>
                <Select
                  id={`hit-decision-${index}`}
                  value={hit.disposition ?? 'OPEN'}
                  onChange={(e) => setHit(index, { disposition: e.target.value as Decision })}
                >
                  {DECISIONS.map((decision) => (
                    <option key={decision} value={decision}>
                      {DISPOSITION_LABEL[decision]}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            {hit.disposition !== 'OPEN' && (
              <Field label="Why" htmlFor={`hit-reason-${index}`} required>
                <Textarea
                  id={`hit-reason-${index}`}
                  rows={2}
                  value={hit.reason ?? ''}
                  onChange={(e) => setHit(index, { reason: e.target.value })}
                />
              </Field>
            )}
            <div className="flex justify-end">
              <Button size="sm" variant="subtle" onClick={() => setHits((prev) => prev.filter((_, i) => i !== index))}>
                Remove
              </Button>
            </div>
          </div>
        ))}
      </div>

      <Field label="Note" htmlFor="sanctions-note">
        <Textarea id="sanctions-note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} />
      </Field>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={record.isPending}>
          Record screening
        </Button>
      </div>
    </form>
  );
}

function HitRow({
  customerId,
  hit,
  canRecord,
}: {
  customerId: string;
  hit: SanctionsHit;
  canRecord: boolean;
}) {
  const action = useSanctionsHitAction(customerId);
  const [deciding, setDeciding] = useState<Decision | 'REJECT' | null>(null);
  const [reason, setReason] = useState('');
  const current = hit.current;
  const proposed = current.disposition === 'TRUE_MATCH_PROPOSED';
  const final = current.disposition === 'TRUE_MATCH';

  async function run(work: Promise<unknown>, done: string) {
    try {
      await work;
      toast.success(done);
      setDeciding(null);
      setReason('');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'That did not work');
    }
  }

  return (
    <li className="py-2.5" data-testid="sanctions-hit">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex flex-wrap items-center gap-2 text-body">
            <span className="font-medium text-ink">{hit.matched_name}</span>
            <span className="text-caption text-ink-3">
              {hit.list_code}
              {hit.list_entry_id ? ` · ${hit.list_entry_id}` : ''}
              {hit.score !== null && hit.score !== undefined ? ` · score ${hit.score}` : ''}
            </span>
            <Badge tone={DISPOSITION_TONE[current.disposition]}>{DISPOSITION_LABEL[current.disposition]}</Badge>
          </p>
          {current.reason && (
            <p className="mt-0.5 text-caption text-ink-2">
              {current.reason} — {current.decided_by_name ?? 'someone'}, {formatDateTime(current.decided_at)}
              {current.approved_by_name && current.disposition === 'TRUE_MATCH'
                ? `; confirmed by ${current.approved_by_name}`
                : ''}
            </p>
          )}
        </div>
        {canRecord && !final && (
          <div className="flex shrink-0 flex-wrap gap-1.5">
            {proposed ? (
              <>
                <Button
                  size="sm"
                  variant="primary"
                  disabled={action.isPending}
                  onClick={() => void run(action.mutateAsync({ action: 'confirm', hitId: hit.id }), 'True match confirmed')}
                >
                  Confirm true match
                </Button>
                <Button size="sm" variant="subtle" onClick={() => setDeciding('REJECT')}>
                  Not a match
                </Button>
              </>
            ) : (
              DECISIONS.filter((decision) => decision !== current.disposition).map((decision) => (
                <Button key={decision} size="sm" variant="subtle" onClick={() => setDeciding(decision)}>
                  {DISPOSITION_LABEL[decision]}
                </Button>
              ))
            )}
          </div>
        )}
      </div>
      {deciding && (
        <div className="mt-2 flex flex-col gap-2 rounded-lg border border-line p-3">
          <Field label={deciding === 'REJECT' ? 'Why it is not a true match' : 'Why'} htmlFor={`decide-${hit.id}`} required>
            <Textarea id={`decide-${hit.id}`} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
          </Field>
          <div className="flex justify-end gap-2">
            <Button size="sm" onClick={() => setDeciding(null)}>
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              disabled={!reason.trim() || action.isPending}
              onClick={() =>
                void run(
                  deciding === 'REJECT'
                    ? action.mutateAsync({ action: 'reject', hitId: hit.id, reason: reason.trim() })
                    : action.mutateAsync({ action: 'decide', hitId: hit.id, disposition: deciding, reason: reason.trim() }),
                  'Decision recorded',
                )
              }
            >
              Save decision
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function RunSummary({ run }: { run: SanctionsRun }) {
  return (
    <p className="text-caption text-ink-3">
      {formatDateTime(run.performed_at)}
      {run.performed_by_name ? ` by ${run.performed_by_name}` : ''} ·{' '}
      {run.lists.map((list) => `${list.code} (${formatDate(list.list_version_date)})`).join(', ')}
    </p>
  );
}

export function SanctionsPanel({ customerId }: { customerId: string }) {
  const query = useCompanySanctions(customerId);
  const [recording, setRecording] = useState<{ subject?: SanctionsSubject } | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const data = query.data;
  const ubos = (data?.subjects ?? []).filter((subject) => subject.subject_type === 'UBO');

  return (
    <Card
      as="h3"
      title="Sanctions screening"
      actions={
        data?.can_record && (
          <Button size="sm" onClick={() => setRecording({})}>
            <Icon.add size={14} /> Record screening
          </Button>
        )
      }
    >
      {recording && (
        <FormPanel title="Record a sanctions screening" onClose={() => setRecording(null)}>
          <RecordForm customerId={customerId} subject={recording.subject} ubos={ubos} onDone={() => setRecording(null)} />
        </FormPanel>
      )}
      {query.isLoading ? (
        <Skeleton className="h-24 rounded-lg" />
      ) : query.isError || !data ? (
        <p className="text-secondary text-negative">Couldn&apos;t load the screening.</p>
      ) : (
        <div className="space-y-3">
          {data.flagged && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-lg border border-negative/40 bg-negative-tint p-3 text-body text-ink"
            >
              <Icon.flagged size={15} className="shrink-0 text-negative" aria-hidden />
              A sanctions true match flags this company. Its deals cannot be handed over.
            </div>
          )}
          <p className="text-body text-ink-2">
            Standing:{' '}
            {data.standing ? (
              <Badge tone={OUTCOME_TONE[data.standing]}>{OUTCOME_LABEL[data.standing]}</Badge>
            ) : (
              <span className="text-ink-3">not screened yet</span>
            )}
          </p>
          <ul className="divide-y divide-line rounded-lg border border-line">
            {data.subjects.map((subject) => {
              const key = `${subject.subject_type}:${subject.subject_reference ?? subject.subject_name}`;
              const latest = subject.latest;
              const due = subject.rescreen_reasons.length > 0;
              return (
                <li key={key} className={`px-4 py-3 ${due ? 'bg-attention-tint' : ''}`} data-testid="sanctions-subject">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div className="min-w-0">
                      <p className="flex flex-wrap items-center gap-2">
                        <span className="font-medium text-ink">{subject.subject_name || 'The company'}</span>
                        <span className="text-caption text-ink-3">{SUBJECT_LABEL[subject.subject_type]}</span>
                        {latest && (
                          <Badge tone={OUTCOME_TONE[latest.outcome]}>{OUTCOME_LABEL[latest.outcome]}</Badge>
                        )}
                      </p>
                      {latest && <RunSummary run={latest} />}
                      {due && (
                        <p className="mt-0.5 text-caption font-medium text-attention">
                          {latest ? 'Re-screen due: ' : ''}
                          {subject.rescreen_reasons.join('; ')}
                        </p>
                      )}
                    </div>
                    <div className="flex shrink-0 gap-2">
                      {latest && latest.hits.length > 0 && (
                        <Button size="sm" variant="subtle" onClick={() => setOpen(open === key ? null : key)}>
                          {open === key ? 'Hide matches' : `Matches (${latest.hits.length})`}
                        </Button>
                      )}
                      {data.can_record && (
                        <Button size="sm" variant="subtle" onClick={() => setRecording({ subject })}>
                          Screen
                        </Button>
                      )}
                    </div>
                  </div>
                  {open === key && latest && (
                    <ul className="mt-2 divide-y divide-line border-t border-line">
                      {latest.hits.map((hit) => (
                        <HitRow key={hit.id} customerId={customerId} hit={hit} canRecord={data.can_record} />
                      ))}
                    </ul>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </Card>
  );
}
