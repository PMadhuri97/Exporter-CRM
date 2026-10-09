/**
 * Companies the CRM cannot identify yet — the identity completion list.
 *
 * A company with no `identity_type` holds neither a PAN nor a registration number, so
 * nothing can match it by identifier and, outside India, it does not meet the
 * foreign-identity rule. The companies the buyer migration created without a number
 * are the expected case. This is a
 * work list, not a filter on the pipeline: it says **what** each company lacks, puts
 * the ones a rule requires first, and a company leaves it as soon as its profile is
 * corrected — completing one is done on the company's own page, with the same edit
 * everyone else uses.
 *
 * It carries no identifier (the companies have none), so every CRM reader sees it;
 * a role that cannot edit sees the list and the company pages, not an edit control.
 */

import { useState } from 'react';

import { Badge, Button, Card, EmptyLine, ErrorState, PageHeader, RecordListItem, Skeleton } from '@/components';
import { formatDate } from '@/lib/format';

import { useIdentityCompletion } from '../hooks';
import { paths } from '../paths';
import type { IdentityCompletionItem } from '../types';
import { countryLabel } from '../countries';

const PAGE_SIZE = 50;
/** `GET /companies/identity-completion` refuses a larger page. */
const MAX_LIMIT = 200;

/** What a company lacks, in the words a person completing it needs. */
const MISSING_LABEL: Record<IdentityCompletionItem['missing'], string> = {
  REGISTRATION_NUMBER: 'Registration number',
  COUNTRY: 'Country',
  PAN: 'PAN',
};

function Row({ item }: { item: IdentityCompletionItem }) {
  return (
    <RecordListItem
      to={paths.company(item.company_id)}
      title={item.name ?? 'Unnamed company'}
      data-testid="identity-completion-row"
      facts={[
        item.country ? countryLabel(item.country) : 'No country',
        item.pipeline_status === 'NOT_IN_PIPELINE' ? 'Buyer only' : null,
        item.created_via === 'DEAL_BUYER' ? 'Created from a deal buyer' : null,
        `Added ${formatDate(item.created_at)}`,
      ]
        .filter(Boolean)
        .join(' · ')}
      badges={<Badge tone={item.required ? 'negative' : 'attention'}>Missing: {MISSING_LABEL[item.missing]}</Badge>}
    />
  );
}

function Group({
  title,
  items,
}: {
  title: string;
  items: IdentityCompletionItem[];
}) {
  if (items.length === 0) return null;
  return (
    <Card title={title} count={items.length} flush aria-label={title}>
      <ul className="divide-y divide-line border-t border-line">
        {items.map((item) => (
          <Row key={item.company_id} item={item} />
        ))}
      </ul>
    </Card>
  );
}

export function IdentityCompletionPage() {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const query = useIdentityCompletion({ limit, offset: 0 });
  const items = query.data?.items ?? [];

  return (
    <div className="flex flex-col gap-4">
      <PageHeader title="Identity to complete" />

      {query.isLoading ? (
        <Skeleton className="h-40" />
      ) : query.isError ? (
        <ErrorState
          title="Couldn't load the companies to complete."
          onRetry={() => void query.refetch()}
        />
      ) : items.length === 0 ? (
        <Card>
          <EmptyLine className="py-0">Every company the CRM holds can be identified.</EmptyLine>
        </Card>
      ) : (
        <>
          <Group
            title="Required"
            items={items.filter((item) => item.required)}
          />
          <Group
            title="Worth completing"
            items={items.filter((item) => !item.required)}
          />
          {query.data && query.data.total > items.length && limit < MAX_LIMIT ? (
            <div className="flex items-center justify-between text-secondary text-ink-3">
              <span>
                Showing {items.length} of {query.data.total}
              </span>
              <Button size="sm" variant="secondary" onClick={() => setLimit(Math.min(limit + PAGE_SIZE, MAX_LIMIT))}>
                Show more
              </Button>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
