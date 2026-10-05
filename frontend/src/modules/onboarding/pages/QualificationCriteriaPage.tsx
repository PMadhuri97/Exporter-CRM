/**
 * Qualification criteria. ADMIN only, guarded at
 * the route (`settings.criteria`): any other role gets the generic NotFound
 * there and never loads this page, so it carries no "Administrators only" of its own.
 *
 * The criteria a lead is qualified against are settings, not code
 * (architecture §3.3): an administrator adds them and changes them here. A
 * criterion is never edited in place — every change, the label included, is a
 * new version, and results keep pointing at the version they were recorded
 * against. So this page offers "Add criterion" and "New version" — each a
 * composer — and shows every earlier version as a trail on the rule's card, but
 * has no edit or delete anywhere.
 *
 * Every rule (key format, a threshold for a number criterion, allowed values
 * for a list) is the server's; a refusal is shown as it worded it. Two admins
 * changing the same criterion at once is caught by the server (409
 * `QUALIFICATION_CRITERION_CHANGED`); the second is asked to reload rather than
 * silently overwriting the first.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  Composer,
  composerFieldError,
  EmptyLine,
  ErrorState,
  Field,
  Input,
  PageHeader,
  Select,
  Skeleton,
  Tag,
} from '@/components';
import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';
import { useCrumbs } from '@/platform/shell';

import {
  useAddCriterionVersion,
  useCreateCriterion,
  useCriteria,
  useCriterionVersions,
} from '../hooks';
import type {
  Criterion,
  CriterionDefinitionRequest,
  CriterionKind,
  ThresholdComparison,
} from '../types';

const FIELDS = ['key', 'label', 'kind', 'comparison', 'threshold', 'unit', 'allowed_values'] as const;

const KIND_LABEL: Record<CriterionKind, string> = {
  NUMBER_THRESHOLD: 'Number threshold',
  YES_NO: 'Yes / no',
  ALLOWED_VALUES: 'Allowed values',
};

const COMPARISON_LABEL: Record<ThresholdComparison, string> = {
  AT_LEAST: 'at least',
  AT_MOST: 'at most',
};

/** The rule in words: "at least 100000 USD", "one of: IN, AE", "yes". */
function ruleOf(criterion: Criterion): string {
  if (criterion.kind === 'NUMBER_THRESHOLD') {
    const comparison = criterion.comparison ? COMPARISON_LABEL[criterion.comparison] : '';
    return [comparison, criterion.threshold, criterion.unit].filter((part) => part !== null && part !== '').join(' ');
  }
  if (criterion.kind === 'ALLOWED_VALUES') {
    return `one of: ${(criterion.allowed_values ?? []).join(', ')}`;
  }
  return 'yes';
}

interface Draft {
  key: string;
  label: string;
  kind: CriterionKind;
  comparison: ThresholdComparison;
  threshold: string;
  unit: string;
  allowedValues: string;
  required: boolean;
  active: boolean;
}

function draftFrom(criterion: Criterion | null): Draft {
  return {
    key: criterion?.key ?? '',
    label: criterion?.label ?? '',
    kind: criterion?.kind ?? 'NUMBER_THRESHOLD',
    comparison: criterion?.comparison ?? 'AT_LEAST',
    threshold: criterion?.threshold?.toString() ?? '',
    unit: criterion?.unit ?? '',
    allowedValues: (criterion?.allowed_values ?? []).join(', '),
    required: criterion?.required ?? true,
    active: criterion?.active ?? true,
  };
}

/** Only the fields the kind uses are sent; the rest go as null. */
function definitionOf(draft: Draft): CriterionDefinitionRequest {
  const threshold = draft.threshold.trim();
  return {
    label: draft.label.trim(),
    kind: draft.kind,
    required: draft.required,
    active: draft.active,
    comparison: draft.kind === 'NUMBER_THRESHOLD' ? draft.comparison : null,
    // Sent as typed when it is not a plain number, so the server refuses it in
    // its own words rather than this page guessing.
    threshold:
      draft.kind === 'NUMBER_THRESHOLD' && threshold
        ? /^-?\d+(\.\d+)?$/.test(threshold)
          ? Number(threshold)
          : threshold
        : null,
    unit: draft.kind === 'NUMBER_THRESHOLD' ? draft.unit.trim() || null : null,
    allowed_values:
      draft.kind === 'ALLOWED_VALUES'
        ? draft.allowedValues
            .split(',')
            .map((value) => value.trim())
            .filter(Boolean)
        : null,
  };
}

/** Add a criterion, or the next version of one — a composer (frontend-plan §6.10). */
function CriterionComposer({
  onClose,
  base,
}: {
  onClose: () => void;
  /** The current version when adding a new one; null when adding a criterion. */
  base: Criterion | null;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(base));
  const create = useCreateCriterion();
  const addVersion = useAddCriterionVersion(base?.key ?? '');
  const mutation = base ? addVersion : create;
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  // Two admins at once: the server refuses the second (409), and the composer says
  // what to do about it rather than only that it failed.
  const stale =
    mutation.error instanceof ApiError && mutation.error.errorCode === 'QUALIFICATION_CRITERION_CHANGED';
  const error = stale
    ? new Error(
        `${mutation.error?.message ?? ''} Someone else changed this criterion — close this and reopen it to start from their version.`,
      )
    : mutation.error;

  const submit = async () => {
    try {
      if (base) {
        const saved = await addVersion.mutateAsync(definitionOf(draft));
        toast.success(`${saved.label}: version ${saved.version} saved`);
      } else {
        const saved = await create.mutateAsync({ key: draft.key.trim(), ...definitionOf(draft) });
        toast.success(`${saved.label} added`);
      }
      onClose();
    } catch {
      // The refusal stays in the composer, in the server's words.
    }
  };

  return (
    <Composer
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title={base ? `New version of “${base.label}”` : 'Add criterion'}
      description={
        base
          ? `Version ${base.version} stays on the record; results already recorded keep pointing at it.`
          : 'Starts at version 1. Every later change is a new version.'
      }
      submitLabel={base ? 'Save new version' : 'Add criterion'}
      pending={mutation.isPending}
      error={error}
      fields={FIELDS}
      onSubmit={() => void submit()}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {!base && (
          <Field
            label="Key"
            htmlFor="criterion-key"
            required
            hint="Permanent. Lower case with underscores, e.g. annual_exports."
            error={composerFieldError(error, 'key')}
            className="sm:col-span-2"
          >
            <Input
              id="criterion-key"
              className="font-mono"
              value={draft.key}
              onChange={(e) => set('key', e.target.value)}
              required
            />
          </Field>
        )}
        <Field
          label="Label"
          htmlFor="criterion-label"
          required
          error={composerFieldError(error, 'label')}
          className="sm:col-span-2"
        >
          <Input id="criterion-label" value={draft.label} onChange={(e) => set('label', e.target.value)} required />
        </Field>
        <Field label="Kind" htmlFor="criterion-kind" required className="sm:col-span-2">
          <Select id="criterion-kind" value={draft.kind} onChange={(e) => set('kind', e.target.value as CriterionKind)}>
            {(Object.keys(KIND_LABEL) as CriterionKind[]).map((kind) => (
              <option key={kind} value={kind}>
                {KIND_LABEL[kind]}
              </option>
            ))}
          </Select>
        </Field>
        {draft.kind === 'NUMBER_THRESHOLD' && (
          <>
            <Field label="Comparison" htmlFor="criterion-comparison">
              <Select
                id="criterion-comparison"
                value={draft.comparison}
                onChange={(e) => set('comparison', e.target.value as ThresholdComparison)}
              >
                <option value="AT_LEAST">At least</option>
                <option value="AT_MOST">At most</option>
              </Select>
            </Field>
            <Field
              label="Threshold"
              htmlFor="criterion-threshold"
              required
              error={composerFieldError(error, 'threshold')}
            >
              <Input
                id="criterion-threshold"
                inputMode="decimal"
                className="font-mono"
                value={draft.threshold}
                onChange={(e) => set('threshold', e.target.value)}
              />
            </Field>
            <Field
              label="Unit"
              htmlFor="criterion-unit"
              hint="e.g. USD, years"
              error={composerFieldError(error, 'unit')}
              className="sm:col-span-2"
            >
              <Input id="criterion-unit" value={draft.unit} onChange={(e) => set('unit', e.target.value)} />
            </Field>
          </>
        )}
        {draft.kind === 'ALLOWED_VALUES' && (
          <Field
            label="Allowed values"
            htmlFor="criterion-values"
            required
            hint="Comma-separated."
            error={composerFieldError(error, 'allowed_values')}
            className="sm:col-span-2"
          >
            <Input
              id="criterion-values"
              value={draft.allowedValues}
              onChange={(e) => set('allowedValues', e.target.value)}
            />
          </Field>
        )}
      </div>
      <div className="space-y-2 border-t border-line pt-4">
        <label className="flex items-center gap-2 text-body text-ink">
          <input
            type="checkbox"
            className="h-4 w-4 accent-ink"
            checked={draft.required}
            onChange={(e) => set('required', e.target.checked)}
          />
          Required for a “Qualified” suggestion
        </label>
        <label className="flex items-center gap-2 text-body text-ink">
          <input
            type="checkbox"
            className="h-4 w-4 accent-ink"
            checked={draft.active}
            onChange={(e) => set('active', e.target.checked)}
          />
          Active
        </label>
      </div>
    </Composer>
  );
}

/**
 * Every version of one criterion, newest first, as a trail down its card. A version
 * is never edited. Who saved it is a user id until the server names people.
 */
function VersionTrail({ criterionKey }: { criterionKey: string }) {
  const versions = useCriterionVersions(criterionKey);
  const rows = [...(versions.data?.criteria ?? [])].sort((a, b) => b.version - a.version);

  if (versions.isLoading) return <Skeleton className="h-20" />;
  if (versions.isError) {
    return (
      <p role="alert" className="text-secondary text-negative">
        Couldn't load the versions.
      </p>
    );
  }
  return (
    <ol className="ml-1.5 space-y-4 border-l border-line pl-5" aria-label={`Versions of ${criterionKey}`}>
      {rows.map((version, index) => (
        <li key={version.id} className="relative" data-testid="criterion-version">
          <span
            aria-hidden
            className={cn(
              'absolute -left-[1.6875rem] top-1 h-2.5 w-2.5 rounded-full border-2 border-surface',
              index === 0 ? 'bg-ink' : 'bg-line-strong',
            )}
          />
          <p className="flex flex-wrap items-center gap-2 text-secondary font-medium text-ink">
            <span className="tabular-nums">v{version.version}</span> · {version.label}
            {!version.active && <Tag>Inactive</Tag>}
          </p>
          <p className="text-secondary text-ink-2">
            {KIND_LABEL[version.kind]} — {ruleOf(version)}
            {version.required ? ' · required' : ''}
          </p>
          <p className="text-caption text-ink-3">
            {formatDateTime(version.created_at)}
            {version.created_by ? (
              <>
                {' · by user id '}
                <span className="font-mono">{version.created_by}</span>
              </>
            ) : null}
          </p>
        </li>
      ))}
    </ol>
  );
}

/** One criterion as a card: the rule in words, its version, and its trail on demand. */
function RuleCard({ criterion, onNewVersion }: { criterion: Criterion; onNewVersion: () => void }) {
  const [showVersions, setShowVersions] = useState(false);
  return (
    <li
      className={cn(
        'flex min-w-0 flex-col gap-3 rounded-xl border bg-surface p-5',
        criterion.active ? 'border-line' : 'border-dashed border-line-strong',
      )}
      data-testid="criterion-row"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-display text-display-sm text-ink">{criterion.label}</p>
          <p className="font-mono text-caption text-ink-3">{criterion.key}</p>
        </div>
        <span className="shrink-0 font-mono text-secondary tabular-nums text-ink-2">v{criterion.version}</span>
      </div>
      <p className="text-lead text-ink">
        <span className="block text-caption text-ink-3">{KIND_LABEL[criterion.kind]}</span>
        {ruleOf(criterion)}
      </p>
      <div className="flex flex-wrap gap-1.5">
        <Tag tone={criterion.active ? 'positive' : 'idle'} dot>
          {criterion.active ? 'Active' : 'Inactive'}
        </Tag>
        {criterion.required && <Tag tone="ink">Required</Tag>}
      </div>
      <div className="mt-auto flex items-center gap-1 border-t border-line pt-3">
        <Button
          size="sm"
          variant="quiet"
          aria-expanded={showVersions}
          onClick={() => setShowVersions((shown) => !shown)}
        >
          <Icon.history size={14} aria-hidden />
          Versions
        </Button>
        <Button
          size="sm"
          className="ml-auto"
          onClick={onNewVersion}
          aria-label={`New version of ${criterion.label}`}
        >
          New version
        </Button>
      </div>
      {showVersions && <VersionTrail criterionKey={criterion.key} />}
    </li>
  );
}

export function QualificationCriteriaPage() {
  const criteria = useCriteria();
  useCrumbs([{ label: 'Settings', to: '/settings' }, { label: 'Qualification criteria' }]);
  // `composerKey` remounts the composer per open, so its draft always starts from
  // the version it was opened on.
  const [composer, setComposer] = useState<{ base: Criterion | null; composerKey: number } | null>(
    null,
  );

  const rows = criteria.data?.criteria ?? [];
  const open = (base: Criterion | null) => setComposer({ base, composerKey: Date.now() });

  return (
    <div className="max-w-reading">
      <PageHeader
        title="Qualification criteria"
        description="What a lead is measured against before someone decides whether it qualifies. Every change is a new version; results keep the version they were recorded against."
        actions={
          <Button variant="primary" onClick={() => open(null)}>
            <Icon.add size={15} aria-hidden />
            Add criterion
          </Button>
        }
      />

      {criteria.isError ? (
        <ErrorState title="Couldn't load the criteria." onRetry={() => void criteria.refetch()} />
      ) : criteria.isLoading ? (
        <div className="grid gap-4 md:grid-cols-2" aria-hidden>
          <Skeleton className="h-48 rounded-xl" />
          <Skeleton className="h-48 rounded-xl" />
        </div>
      ) : rows.length === 0 ? (
        <EmptyLine>No criteria yet — add the first one.</EmptyLine>
      ) : (
        <ul className="grid items-start gap-4 md:grid-cols-2" aria-label="Criteria">
          {rows.map((criterion) => (
            <RuleCard key={criterion.key} criterion={criterion} onNewVersion={() => open(criterion)} />
          ))}
        </ul>
      )}

      <p className="mt-6 text-caption text-ink-3">
        Reason codes for “Not qualified” are managed on the server; there is no screen for them yet.
      </p>

      {composer && (
        <CriterionComposer
          key={composer.composerKey}
          base={composer.base}
          onClose={() => setComposer(null)}
        />
      )}
    </div>
  );
}
