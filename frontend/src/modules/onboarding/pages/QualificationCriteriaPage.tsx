/**
 * Qualification criteria — **owner: Developer 2** (L2-09). ADMIN only, guarded at
 * the route (`settings.criteria`, R-33 G5): any other role gets the generic NotFound
 * there and never loads this page, so it carries no "Administrators only" of its own.
 *
 * The criteria a lead is qualified against are settings, not code
 * (architecture §3.3): an administrator adds them and changes them here. A
 * criterion is never edited in place — every change, the label included, is a
 * new version, and results keep pointing at the version they were recorded
 * against. So this page offers "Add criterion" and "New version", and shows
 * every earlier version, but has no edit or delete anywhere.
 *
 * Every rule (key format, a threshold for a number criterion, allowed values
 * for a list) is the server's; a refusal is shown as it worded it. Two admins
 * changing the same criterion at once is caught by the server (409
 * `QUALIFICATION_CRITERION_CHANGED`); the second is asked to reload rather than
 * silently overwriting the first.
 */

import { History as HistoryIcon, Plus } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  Card,
  Chip,
  Dialog,
  Drawer,
  EmptySection,
  ErrorState,
  Field,
  FormError,
  Input,
  PageHeader,
  Select,
  Skeleton,
  Table,
  TBody,
  Td,
  Th,
  THead,
  Tr,
} from '@/components';
import { ApiError } from '@/lib/api/errors';
import { formatDateTime } from '@/lib/format';

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

/** Add a criterion, or add the next version of one. */
function CriterionDialog({
  open,
  onClose,
  base,
}: {
  open: boolean;
  onClose: () => void;
  /** The current version when adding a new one; null when adding a criterion. */
  base: Criterion | null;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftFrom(base));
  const [error, setError] = useState<{ message: string; stale: boolean } | null>(null);
  const create = useCreateCriterion();
  const addVersion = useAddCriterionVersion(base?.key ?? '');
  const mutation = base ? addVersion : create;
  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      if (base) {
        const saved = await addVersion.mutateAsync(definitionOf(draft));
        toast.success(`${saved.label}: version ${saved.version} saved`);
      } else {
        const saved = await create.mutateAsync({ key: draft.key.trim(), ...definitionOf(draft) });
        toast.success(`${saved.label} added`);
      }
      onClose();
    } catch (caught) {
      setError({
        message: caught instanceof Error ? caught.message : 'Could not save the criterion.',
        stale: caught instanceof ApiError && caught.errorCode === 'QUALIFICATION_CRITERION_CHANGED',
      });
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      size="lg"
      title={base ? `New version of “${base.label}”` : 'Add criterion'}
      description={
        base
          ? `Version ${base.version} stays on the record; results already recorded keep pointing at it.`
          : 'Starts at version 1. Every later change is a new version.'
      }
    >
      <form onSubmit={(event) => void submit(event)} className="space-y-4" aria-label="Criterion">
        {error && (
          <FormError>
            {error.message}
            {error.stale && ' Someone else changed this criterion — close this and reopen it to start from their version.'}
          </FormError>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          {!base && (
            <Field label="Key" htmlFor="criterion-key" required hint="Permanent. Lower case with underscores, e.g. annual_exports.">
              <Input id="criterion-key" value={draft.key} onChange={(e) => set('key', e.target.value)} required />
            </Field>
          )}
          <Field label="Label" htmlFor="criterion-label" required className={base ? 'sm:col-span-2' : undefined}>
            <Input id="criterion-label" value={draft.label} onChange={(e) => set('label', e.target.value)} required />
          </Field>
          <Field label="Kind" htmlFor="criterion-kind" required>
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
              <Field label="Threshold" htmlFor="criterion-threshold" required>
                <Input
                  id="criterion-threshold"
                  inputMode="decimal"
                  value={draft.threshold}
                  onChange={(e) => set('threshold', e.target.value)}
                />
              </Field>
              <Field label="Unit" htmlFor="criterion-unit" hint="e.g. USD, years">
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
        <div className="flex flex-wrap gap-6">
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="h-4 w-4 accent-brand-600"
              checked={draft.required}
              onChange={(e) => set('required', e.target.checked)}
            />
            Required for a “Qualified” suggestion
          </label>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              className="h-4 w-4 accent-brand-600"
              checked={draft.active}
              onChange={(e) => set('active', e.target.checked)}
            />
            Active
          </label>
        </div>
        <div className="flex justify-end gap-2 border-t border-border pt-4">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={mutation.isPending}>
            {base ? 'Save new version' : 'Add criterion'}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function VersionsDrawer({ criterionKey, onClose }: { criterionKey: string | null; onClose: () => void }) {
  const versions = useCriterionVersions(criterionKey);
  const rows = [...(versions.data?.criteria ?? [])].sort((a, b) => b.version - a.version);

  return (
    <Drawer
      open={criterionKey !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={`Versions of ${criterionKey ?? ''}`}
      description="Newest first. A version is never edited."
    >
      {versions.isLoading && <Skeleton className="h-32" />}
      {versions.isError && <p className="text-sm text-status-failed">Couldn't load the versions.</p>}
      <ol className="space-y-3">
        {rows.map((version) => (
          <li key={version.id} className="rounded-lg border border-border p-3" data-testid="criterion-version">
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium text-ink">
                v{version.version} · {version.label}
              </span>
              {!version.active && <Chip>Inactive</Chip>}
            </div>
            <p className="mt-1 text-sm text-ink-muted">
              {KIND_LABEL[version.kind]} — {ruleOf(version)}
              {version.required ? ' · required' : ''}
            </p>
            <p className="mt-1 text-xs text-ink-faint">
              {formatDateTime(version.created_at)}
              {version.created_by ? ` · ${version.created_by}` : ''}
            </p>
          </li>
        ))}
      </ol>
    </Drawer>
  );
}

export function QualificationCriteriaPage() {
  const criteria = useCriteria();
  // `dialogKey` remounts the dialog per open, so its draft always starts from
  // the version it was opened on.
  const [dialog, setDialog] = useState<{ base: Criterion | null; dialogKey: number } | null>(null);
  const [versionsOf, setVersionsOf] = useState<string | null>(null);

  const rows = criteria.data?.criteria ?? [];
  const open = (base: Criterion | null) => setDialog({ base, dialogKey: Date.now() });

  return (
    <div>
      <PageHeader
        title="Qualification criteria"
        description="What a lead is measured against before someone decides whether it qualifies. Every change is a new version; results keep the version they were recorded against."
        actions={
          <Button variant="primary" onClick={() => open(null)}>
            <Plus size={15} />
            Add criterion
          </Button>
        }
      />

      <Card>
        {criteria.isError ? (
          <ErrorState title="Couldn't load the criteria." className="m-4" onRetry={() => void criteria.refetch()} />
        ) : criteria.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : rows.length === 0 ? (
          <div className="p-4">
            <EmptySection>No criteria yet — add the first one.</EmptySection>
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Criterion</Th>
                <Th>Kind</Th>
                <Th>Rule</Th>
                <Th>Status</Th>
                <Th className="text-right">Version</Th>
                <Th>
                  <span className="sr-only">Actions</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {rows.map((criterion) => (
                <Tr key={criterion.key} data-testid="criterion-row">
                  <Td>
                    <p className="font-medium text-ink">{criterion.label}</p>
                    <p className="font-mono text-xs text-ink-faint">{criterion.key}</p>
                  </Td>
                  <Td className="text-ink-muted">{KIND_LABEL[criterion.kind]}</Td>
                  <Td className="text-ink-muted">{ruleOf(criterion)}</Td>
                  <Td>
                    <span className="flex flex-wrap gap-1">
                      <Chip tone={criterion.active ? 'success' : 'neutral'}>
                        {criterion.active ? 'Active' : 'Inactive'}
                      </Chip>
                      {criterion.required && <Chip tone="info">Required</Chip>}
                    </span>
                  </Td>
                  <Td className="text-right tabular-nums">v{criterion.version}</Td>
                  <Td className="text-right">
                    <span className="inline-flex gap-1">
                      <Button size="sm" variant="ghost" onClick={() => setVersionsOf(criterion.key)}>
                        <HistoryIcon size={14} />
                        Versions
                      </Button>
                      <Button
                        size="sm"
                        onClick={() => open(criterion)}
                        aria-label={`New version of ${criterion.label}`}
                      >
                        New version
                      </Button>
                    </span>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <p className="mt-3 text-xs text-ink-faint">
        Reason codes for “Not qualified” are managed on the server; there is no screen for them yet.
      </p>

      {dialog && (
        <CriterionDialog
          key={dialog.dialogKey}
          open
          base={dialog.base}
          onClose={() => setDialog(null)}
        />
      )}
      <VersionsDrawer criterionKey={versionsOf} onClose={() => setVersionsOf(null)} />
    </div>
  );
}
