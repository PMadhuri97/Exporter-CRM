/**
 * Required documents for a handover.
 * ADMIN only, guarded at the route (`settings.requiredDocuments`): any other
 * role gets the generic NotFound there and never loads this page.
 *
 * Which paperwork a deal must have before it goes to the lending team is a
 * setting, not code: an administrator adds and removes categories here, and the
 * handover guard reads them (deal contract §6.1 condition 3).
 *
 * **Nothing is ever edited or deleted.** Removing a requirement writes a new
 * version saying it is no longer required, so the record of what was required
 * when survives — a deal handed over last month was judged against the rule as it
 * stood then. So this page offers "Require" and "Stop requiring", and shows every
 * earlier version, but has no edit or delete anywhere. The same shape as
 * `QualificationCriteriaPage`, for the same reason.
 *
 * Laid out as the deal's categories, one row each (frontend-plan §8.9): a mark
 * says whether the category is required, the requirements recorded for it sit in
 * its row, and the change history runs underneath.
 *
 * Every rule is the server's: which categories a deal may hold, and that a change
 * must actually change something. A refusal is shown as the server worded it; two
 * administrators changing the same requirement at once is caught by the server
 * (409 `DEAL_REQUIRED_DOCUMENT_CHANGED`), and the second is told someone changed it.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Button,
  Card,
  SidePanel,
  EmptyLine,
  ErrorState,
  Field,
  PageHeader,
  Panel,
  Select,
  Skeleton,
  Tag,
  RequiredNote,
} from '@/components';
import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { cn } from '@/lib/cn';
import { formatDateTime } from '@/lib/format';

import {
  useDealRequiredDocuments,
  useDocumentCategories,
  useSetDealRequiredDocument,
} from '../hooks';
import type { DealRequiredDocument } from '../types';

/**
 * The categories a **deal** may hold — architecture §3.4's "Belongs to" column
 * for `DEAL` and `BOTH`. The server refuses the others (422), so this list only
 * keeps an administrator from being offered a choice that cannot work.
 *
 * Spelled out rather than derived from the document catalogue: the catalogue says
 * which categories exist, not which may be required of a deal, and the server is
 * the authority on that either way.
 */
const DEAL_CATEGORIES: { value: string; label: string }[] = [
  { value: 'PRE_SHIPMENT', label: 'Pre-shipment (invoice, PO, contract, LC)' },
  { value: 'SHIPPING', label: 'Shipping (bill of lading, packing list)' },
  { value: 'CUSTOMS_AND_REGULATORY', label: 'Customs and regulatory' },
  { value: 'BUYER', label: 'Buyer (rating report, buyer KYC)' },
  { value: 'BANKING', label: 'Banking (FIRC, e-BRC)' },
  { value: 'INSURANCE', label: 'Insurance' },
  { value: 'OTHER', label: 'Other' },
];

const CATEGORY_LABEL = new Map(DEAL_CATEGORIES.map((c) => [c.value, c.label]));

const SOMEONE_CHANGED =
  'Someone else changed this requirement first, so nothing was saved. The list now shows their change — look again before you decide.';

const HISTORY_PREVIEW = 6;

/** How one requirement reads. `document_type` is `null` for "any type". */
function describe(row: DealRequiredDocument): string {
  const label = CATEGORY_LABEL.get(row.category) ?? row.category;
  return row.document_type ? `${label} — ${row.document_type} only` : label;
}

function isStale(error: unknown): boolean {
  return error instanceof ApiError && error.errorCode === 'DEAL_REQUIRED_DOCUMENT_CHANGED';
}

/** "Require a document before handover" — a composer, opened on a category or none. */
function RequireComposer({ initialCategory, onClose }: { initialCategory: string; onClose: () => void }) {
  const mutation = useSetDealRequiredDocument();
  // The types a deal may upload in each category — the same list the upload route
  // checks, so a requirement can only name a type a deal could actually provide.
  const catalogue = useDocumentCategories('DEAL');
  const [category, setCategory] = useState(initialCategory);
  const [documentType, setDocumentType] = useState('');
  const types =
    catalogue.data?.categories.find((option) => option.category === category)?.types ?? [];
  const error = isStale(mutation.error) ? new Error(SOMEONE_CHANGED) : mutation.error;

  async function submit() {
    try {
      await mutation.mutateAsync({
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the server validates the value
        category: category as any,
        document_type: documentType || null,
        active: true,
      });
      toast.success('Requirement added');
      onClose();
    } catch {
      // The refusal stays in the composer, in the server's words.
    }
  }

  return (
    <SidePanel
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title="Require a document before handover"
      submitLabel="Add requirement"
      pending={mutation.isPending}
      error={error}
      submitDisabled={category === ''}
      onSubmit={() => void submit()}
    >
      <RequiredNote />
      <Field label="Category" htmlFor="required-category" required>
        <Select
          id="required-category"
          required
          value={category}
          onChange={(event) => {
            setCategory(event.target.value);
            // A type belongs to one category; keep it and the server refuses it.
            setDocumentType('');
          }}
        >
          <option value="">Choose a category…</option>
          {DEAL_CATEGORIES.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </Select>
      </Field>

      <Field
        label="Document type"
        htmlFor="required-type"
        hint="“Any type” is met by any document in the category. Choose a type to insist on that one — only the types the document settings configure for the category are offered, because a deal could never upload any other."
      >
        <Select
          id="required-type"
          value={documentType}
          disabled={category === ''}
          onChange={(event) => setDocumentType(event.target.value)}
        >
          <option value="">Any type in the category</option>
          {types.map((type) => (
            <option key={type.key} value={type.key}>
              {type.label}
            </option>
          ))}
        </Select>
      </Field>

      <p className="rounded-md border-l-2 border-attention-solid bg-attention-tint px-3 py-2 text-secondary text-ink">
        This changes which deals can be handed over. A deal with no scanned-clean document
        in this category will be refused, naming it. Deals already handed over are
        unaffected.
      </p>
    </SidePanel>
  );
}

/** Required or not, at a glance: a filled blue circle with a tick, or an empty ring. */
function RequiredLamp({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={cn(
        'mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full',
        on ? 'bg-accent-solid text-white' : 'border border-dashed border-line-strong',
      )}
    >
      {on && <Icon.check size={12} />}
    </span>
  );
}

function History({ rows }: { rows: DealRequiredDocument[] }) {
  const [all, setAll] = useState(false);
  const sorted = [...rows].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const shown = all ? sorted : sorted.slice(0, HISTORY_PREVIEW);

  if (sorted.length === 0) return <EmptyLine>Nothing has changed since the rule was seeded.</EmptyLine>;
  return (
    <>
      <ol className="divide-y divide-line" aria-label="Every change to this rule">
        {shown.map((row) => (
          <li key={row.id} className="grid grid-cols-[9rem_minmax(0,1fr)] gap-4 py-2.5">
            <span className="text-caption tabular-nums text-ink-3">{formatDateTime(row.created_at)}</span>
            <span className="min-w-0">
              <span className="flex flex-wrap items-center gap-2 text-secondary text-ink">
                {describe(row)}
                <Tag tone={row.active ? 'ink' : 'idle'}>{row.active ? 'Required' : 'Not required'}</Tag>
              </span>
              <span className="block text-caption text-ink-3">
                Version {row.version}
                {row.created_by ? (
                  <>
                    {' · by user id '}
                    <span className="">{row.created_by}</span>
                  </>
                ) : (
                  ' · seeded'
                )}
              </span>
            </span>
          </li>
        ))}
      </ol>
      {sorted.length > HISTORY_PREVIEW && (
        <Button size="sm" variant="subtle" className="mt-2" onClick={() => setAll((shownAll) => !shownAll)}>
          {all ? 'Show the latest only' : `Show all ${sorted.length} changes`}
        </Button>
      )}
    </>
  );
}

export function DealRequiredDocumentsPage() {
  const rule = useDealRequiredDocuments();
  const mutation = useSetDealRequiredDocument();
  // `''` opens the composer with no category chosen; a value opens it on that one.
  const [requiring, setRequiring] = useState<string | null>(null);

  const requirements = rule.data?.requirements ?? [];
  const history = rule.data?.history ?? [];
  // A category the server returned that this page does not list still shows.
  const categories = [
    ...DEAL_CATEGORIES,
    ...requirements
      .filter((row) => !CATEGORY_LABEL.has(row.category))
      .map((row) => ({ value: row.category, label: row.category })),
  ];

  async function stopRequiring(row: DealRequiredDocument) {
    try {
      await mutation.mutateAsync({
        category: row.category,
        document_type: row.document_type,
        active: false,
      });
      toast.success('Requirement removed');
    } catch (caught) {
      if (isStale(caught)) {
        void rule.refetch();
        toast.error(SOMEONE_CHANGED);
        return;
      }
      toast.error(caught instanceof Error ? caught.message : 'Could not remove the requirement');
    }
  }

  return (
    <div className="max-w-reading">
      <PageHeader
        as="h2"
        title="Required documents"
        actions={
          <Button variant="primary" onClick={() => setRequiring('')}>
            <Icon.add size={15} aria-hidden />
            Require a category
          </Button>
        }
      />

      {rule.isError ? (
        <ErrorState title="Couldn't load the rule." onRetry={() => void rule.refetch()} />
      ) : rule.isLoading ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : (
        <div className="space-y-4">
          <Card title="Categories" as="h3" flush>
            {requirements.every((row) => !row.active) && (
              <EmptyLine className="px-4 pb-3">
                Nothing is required yet — a deal can be handed over with no paperwork on file.
              </EmptyLine>
            )}
            <ul className="divide-y divide-line border-t border-line" aria-label="Deal document categories">
              {categories.map((category) => {
                const rows = requirements.filter((row) => row.category === category.value);
                const required = rows.some((row) => row.active);
                const anyTypeRequired = rows.some((row) => row.active && row.document_type === null);
                return (
                  <li key={category.value} className="flex items-start gap-3 px-4 py-3" data-testid="category-row">
                    <RequiredLamp on={required} />
                    <div className="min-w-0 flex-1">
                      {rows.length === 0 ? (
                        <>
                          <p className="text-body text-ink-2">{category.label}</p>
                          <p className="text-caption text-ink-3">Not required</p>
                        </>
                      ) : (
                        <ul className="space-y-2">
                          {rows.map((row) => (
                            <li
                              key={row.id}
                              className="flex flex-wrap items-center gap-x-3 gap-y-1"
                              data-testid="requirement-row"
                            >
                              <span className="min-w-0 text-body font-medium text-ink">{describe(row)}</span>
                              <Tag tone={row.active ? 'ink' : 'idle'}>{row.active ? 'Required' : 'Not required'}</Tag>
                              <span className="text-caption tabular-nums text-ink-3">v{row.version}</span>
                              {/* Only an active requirement can be removed; an inactive row
                                  is shown because it was removed, and "remove" again would
                                  be refused by the server. */}
                              {row.active && (
                                <Button
                                  size="sm"
                                  variant="subtle"
                                  className="ml-auto"
                                  disabled={mutation.isPending}
                                  onClick={() => void stopRequiring(row)}
                                >
                                  Stop requiring
                                </Button>
                              )}
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    {!anyTypeRequired && (
                      <Button
                        size="sm"
                        onClick={() => setRequiring(category.value)}
                        aria-label={`Require ${category.label}`}
                      >
                        Require
                      </Button>
                    )}
                  </li>
                );
              })}
            </ul>
          </Card>

          <Panel as="h3" title="Every change">
            <History rows={history} />
          </Panel>
        </div>
      )}

      {requiring !== null && (
        <RequireComposer initialCategory={requiring} onClose={() => setRequiring(null)} />
      )}
    </div>
  );
}
