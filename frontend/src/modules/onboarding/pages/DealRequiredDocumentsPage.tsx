/**
 * Required documents for a handover — **owner: Developer 2** (plan P2-5a).
 * ADMIN only.
 *
 * Which paperwork a deal must have before it goes to the lending team is a
 * setting, not code: an administrator adds and removes categories here, and the
 * handover guard reads them (deal contract §6.1 condition 3).
 *
 * **Nothing is ever edited or deleted.** Removing a requirement writes a new
 * version saying it is no longer required, so the record of what was required
 * when survives — a deal handed over last month was judged against the rule as it
 * stood then. So this page offers "Require a category" and "Stop requiring", and
 * shows every earlier version, but has no edit or delete anywhere. The same shape
 * as `QualificationCriteriaPage`, for the same reason.
 *
 * Every rule is the server's: which categories a deal may hold, and that a change
 * must actually change something. A refusal is shown as the server worded it.
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
  NotFound,
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
import { isAdminRole, useCurrentUser } from '@/platform/auth';

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

/** How one requirement reads. `document_type` is `null` for "any type". */
function describe(row: DealRequiredDocument): string {
  const label = CATEGORY_LABEL.get(row.category) ?? row.category;
  return row.document_type ? `${label} — ${row.document_type} only` : label;
}

function AddDialog({ onClose }: { onClose: () => void }) {
  const mutation = useSetDealRequiredDocument();
  // The types a deal may upload in each category — the same list the upload route
  // checks, so a requirement can only name a type a deal could actually provide.
  const catalogue = useDocumentCategories('DEAL');
  const [category, setCategory] = useState('');
  const [documentType, setDocumentType] = useState('');
  const [error, setError] = useState<string | null>(null);
  const types =
    catalogue.data?.categories.find((option) => option.category === category)?.types ?? [];

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    try {
      await mutation.mutateAsync({
        // eslint-disable-next-line @typescript-eslint/no-explicit-any -- the server validates the value
        category: category as any,
        document_type: documentType || null,
        active: true,
      });
      toast.success('Requirement added');
      onClose();
    } catch (caught) {
      setError(
        caught instanceof ApiError || caught instanceof Error
          ? caught.message
          : 'Could not add the requirement',
      );
    }
  }

  return (
    <Dialog open onOpenChange={onClose} title="Require a document before handover">
      <form onSubmit={submit} className="flex flex-col gap-3">
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

        <Field label="Document type (optional)" htmlFor="required-type">
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
        <p className="text-xs text-ink-faint">
          &ldquo;Any type&rdquo; is met by any document in the category. Choose a type to
          insist on that one — only the types the document settings configure for the
          category are offered, because a deal could never upload any other.
        </p>

        {error !== null && <FormError>{error}</FormError>}

        <p className="rounded-lg border border-status-review/30 bg-status-review/10 px-3 py-2 text-xs text-ink">
          This changes which deals can be handed over. A deal with no scanned-clean
          document in this category will be refused, naming it. Deals already handed
          over are unaffected.
        </p>

        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            type="submit"
            variant="primary"
            disabled={category === ''}
            loading={mutation.isPending}
          >
            Add requirement
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function HistoryDrawer({
  rows,
  onClose,
}: {
  rows: DealRequiredDocument[];
  onClose: () => void;
}) {
  return (
    <Drawer open onOpenChange={onClose} title="Every change to this rule">
      {rows.length === 0 ? (
        <EmptySection>Nothing has changed since the rule was seeded.</EmptySection>
      ) : (
        <ol className="space-y-3">
          {rows.map((row) => (
            <li key={row.id} className="border-b border-border pb-3 last:border-0">
              <p className="text-sm font-medium text-ink">
                {describe(row)}{' '}
                <Chip tone={row.active ? 'success' : 'neutral'}>
                  {row.active ? 'Required' : 'Not required'}
                </Chip>
              </p>
              <p className="mt-0.5 text-xs text-ink-faint">
                Version {row.version} · {formatDateTime(row.created_at)}
                {row.created_by ? ` · ${row.created_by}` : ' · seeded'}
              </p>
            </li>
          ))}
        </ol>
      )}
    </Drawer>
  );
}

export function DealRequiredDocumentsPage() {
  const { role } = useCurrentUser();
  const rule = useDealRequiredDocuments();
  const mutation = useSetDealRequiredDocument();
  const [adding, setAdding] = useState(false);
  const [showingHistory, setShowingHistory] = useState(false);

  // The same gate the criteria page uses: the server refuses the write anyway,
  // and a screen that offered it would be promising something it cannot do.
  if (!isAdminRole(role)) {
    return (
      <NotFound title="Administrators only">
        Which documents a handover needs is managed by an administrator.
      </NotFound>
    );
  }

  const requirements = rule.data?.requirements ?? [];
  const history = rule.data?.history ?? [];

  async function stopRequiring(row: DealRequiredDocument) {
    try {
      await mutation.mutateAsync({
        category: row.category,
        document_type: row.document_type,
        active: false,
      });
      toast.success('Requirement removed');
    } catch (caught) {
      toast.error(
        caught instanceof Error ? caught.message : 'Could not remove the requirement',
      );
    }
  }

  return (
    <div>
      <PageHeader
        title="Required documents"
        description="What a deal must have on file before it can be handed to the lending team. Every change is a new version; a deal already handed over is never re-judged."
        actions={
          <span className="flex gap-2">
            <Button variant="secondary" onClick={() => setShowingHistory(true)}>
              <HistoryIcon size={15} />
              History
            </Button>
            <Button variant="primary" onClick={() => setAdding(true)}>
              <Plus size={15} />
              Require a category
            </Button>
          </span>
        }
      />

      <Card>
        {rule.isError ? (
          <ErrorState
            title="Couldn't load the rule."
            className="m-4"
            onRetry={() => void rule.refetch()}
          />
        ) : rule.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-10" />
            <Skeleton className="h-10" />
          </div>
        ) : requirements.length === 0 ? (
          <div className="p-4">
            <EmptySection>
              Nothing is required yet — a deal can be handed over with no paperwork on
              file.
            </EmptySection>
          </div>
        ) : (
          <Table>
            <THead>
              <tr>
                <Th>Requirement</Th>
                <Th>Status</Th>
                <Th className="text-right">Version</Th>
                <Th>
                  <span className="sr-only">Actions</span>
                </Th>
              </tr>
            </THead>
            <TBody>
              {requirements.map((row) => (
                <Tr key={row.id} data-testid="requirement-row">
                  <Td>
                    <p className="font-medium text-ink">{describe(row)}</p>
                    <p className="font-mono text-xs text-ink-faint">
                      {row.category}
                      {row.document_type ? ` · ${row.document_type}` : ''}
                    </p>
                  </Td>
                  <Td>
                    <Chip tone={row.active ? 'success' : 'neutral'}>
                      {row.active ? 'Required' : 'Not required'}
                    </Chip>
                  </Td>
                  <Td className="text-right text-ink-muted">{row.version}</Td>
                  <Td className="text-right">
                    {/* Only an active requirement can be removed; an inactive row
                        is shown because it was removed, and "remove" again would
                        be refused by the server. */}
                    {row.active && (
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={mutation.isPending}
                        onClick={() => void stopRequiring(row)}
                      >
                        Stop requiring
                      </Button>
                    )}
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {adding && <AddDialog onClose={() => setAdding(false)} />}
      {showingHistory && (
        <HistoryDrawer rows={history} onClose={() => setShowingHistory(false)} />
      )}
    </div>
  );
}
