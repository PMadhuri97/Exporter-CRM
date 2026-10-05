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
import { Link } from 'react-router-dom';

import { Button, EmptyLine, ErrorState, PageHeader, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { useIdentityCompletion } from '../hooks';
import { paths } from '../paths';
import type { IdentityCompletionItem } from '../types';

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
    <li data-testid="identity-completion-row">
      <Link
        to={paths.company(item.company_id)}
        className="group flex flex-wrap items-center justify-between gap-3 py-3"
      >
        <span className="min-w-0">
          <span className="block truncate font-display text-display-sm text-ink underline-offset-4 group-hover:underline">
            {item.name ?? 'Unnamed company'}
          </span>
          <span className="mt-0.5 block text-secondary text-ink-3">
            {item.country ?? 'No country'}
            {item.pipeline_status === 'NOT_IN_PIPELINE' ? ' · Buyer only' : ''}
            {item.created_via === 'DEAL_BUYER' ? ' · Created from a deal buyer' : ''}
            {` · Added ${formatDate(item.created_at)}`}
          </span>
        </span>
        <span className="inline-flex items-center gap-1.5 text-secondary font-medium text-attention">
          Needs: {MISSING_LABEL[item.missing]}
          <Icon.forward size={13} className="text-ink-3" aria-hidden />
        </span>
      </Link>
    </li>
  );
}

function Group({
  title,
  description,
  items,
}: {
  title: string;
  description: string;
  items: IdentityCompletionItem[];
}) {
  if (items.length === 0) return null;
  return (
    <section aria-label={title} className="flex flex-col gap-1 border-t border-line pt-4">
      <h2 className="text-lead font-semibold text-ink">{title}</h2>
      <p className="text-secondary text-ink-3">{description}</p>
      <ul className="mt-1 divide-y divide-line">
        {items.map((item) => (
          <Row key={item.company_id} item={item} />
        ))}
      </ul>
    </section>
  );
}

export function IdentityCompletionPage() {
  const [limit, setLimit] = useState(PAGE_SIZE);
  const query = useIdentityCompletion({ limit, offset: 0 });
  const items = query.data?.items ?? [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        title="Identity to complete"
        description="Companies the CRM cannot identify: they hold neither a PAN nor a registration number. Add the missing identifier on the company's page and it leaves this list."
      />

      {query.isLoading ? (
        <Skeleton className="h-40 rounded-lg" />
      ) : query.isError ? (
        <ErrorState
          title="Couldn't load the companies to complete."
          onRetry={() => void query.refetch()}
        />
      ) : items.length === 0 ? (
        <EmptyLine>Every company the CRM holds can be identified.</EmptyLine>
      ) : (
        <>
          <Group
            title="Required"
            description="A company outside India must carry its registration number, and every company needs a country."
            items={items.filter((item) => item.required)}
          />
          <Group
            title="Worth completing"
            description="Indian companies with no PAN. Not required, but they cannot be matched by identifier until they have one."
            items={items.filter((item) => !item.required)}
          />
          {query.data && query.data.total > items.length && limit < MAX_LIMIT ? (
            <div className="flex items-center justify-between border-t border-line pt-3 text-secondary text-ink-3">
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
