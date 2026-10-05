/**
 * The company record's right column (frontend-plan §6.6, §8.5): related records as
 * cards, three items each, as Salesforce shows related lists in a narrow column —
 * open follow-ups, deals, contacts and documents. *View all* opens the matching tab;
 * *+ Add* on Contacts is offered only to a role that may write (Developer reads).
 *
 * Every list is the server's, capped at three here; the count beside each title is
 * the server's total, not the length of what is shown.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Badge, Button, Card, EmptyLine, FormPanel, Input, Skeleton } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate, formatDateTime } from '@/lib/format';

import { useAddExporterContact, useCompanyDeals, useCompanyDocuments, useFollowUps } from '../hooks';
import { paths } from '../paths';
import type { AddExporterContactRequest, ExporterContact } from '../types';

import { categoryLabel } from './record/categoryLabel';
import { DealStageChip } from './DealStageChip';
import { ScanStatusBadge } from './ScanStatusBadge';

const SHOWN = 3;

function Item({
  title,
  to,
  detail,
  badge,
}: {
  title: string;
  to?: string;
  detail?: string;
  badge?: React.ReactNode;
}) {
  return (
    <li className="flex items-start justify-between gap-3 py-2">
      <div className="min-w-0">
        {to ? (
          <Link to={to} className="block truncate text-body font-semibold text-accent underline-offset-2 hover:underline">
            {title}
          </Link>
        ) : (
          <p className="truncate text-body font-semibold text-ink">{title}</p>
        )}
        {detail && <p className="truncate text-secondary text-ink-2">{detail}</p>}
      </div>
      {badge && <span className="shrink-0">{badge}</span>}
    </li>
  );
}

function List({ children }: { children: React.ReactNode }) {
  return <ul className="-my-2 divide-y divide-line">{children}</ul>;
}

function Loading() {
  return (
    <div className="space-y-2" aria-hidden>
      <Skeleton className="h-9" />
      <Skeleton className="h-9" />
    </div>
  );
}

function FollowUpsCard({ customerId }: { customerId: string }) {
  const query = useFollowUps({ customerId, state: 'OUTSTANDING', includeCheckBacks: false, limit: SHOWN });
  const items = query.data?.follow_ups ?? [];
  return (
    <Card
      as="h3"
      title="Open follow-ups"
      count={query.data?.follow_ups_total}
      footer={{ label: 'View all', to: paths.company(customerId, 'conversation') }}
    >
      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <p className="text-secondary text-negative">Couldn&apos;t load follow-ups.</p>
      ) : items.length === 0 ? (
        <EmptyLine className="py-0">No follow-ups due.</EmptyLine>
      ) : (
        <List>
          {items.map((item) => (
            <Item
              key={item.activity_id}
              title={item.subject}
              detail={[item.due_at ? `Due ${formatDate(item.due_at)}` : null, item.actor_name].filter(Boolean).join(' · ')}
              badge={item.is_overdue ? <Badge tone="negative">Overdue</Badge> : undefined}
            />
          ))}
        </List>
      )}
    </Card>
  );
}

function DealsCard({ customerId }: { customerId: string }) {
  const query = useCompanyDeals(customerId);
  const deals = query.data?.deals ?? [];
  return (
    <Card
      as="h3"
      title="Deals"
      count={query.data?.total}
      footer={{ label: 'View all', to: paths.company(customerId, 'deals') }}
    >
      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <p className="text-secondary text-negative">Couldn&apos;t load deals.</p>
      ) : deals.length === 0 ? (
        <EmptyLine className="py-0">No deals yet.</EmptyLine>
      ) : (
        <List>
          {deals.slice(0, SHOWN).map((deal) => (
            <Item
              key={deal.id}
              title={deal.reference ?? 'Deal'}
              to={paths.deal(deal.id)}
              detail={deal.buyer_name ? `Buyer: ${deal.buyer_name}` : `Opened ${formatDate(deal.created_at)}`}
              badge={<DealStageChip stage={deal.stage} />}
            />
          ))}
        </List>
      )}
    </Card>
  );
}

/** Adding a person: their name, and whatever else is known. */
function AddContactForm({ customerId, onDone }: { customerId: string; onDone: () => void }) {
  const mutation = useAddExporterContact(customerId);
  const [form, setForm] = useState<AddExporterContactRequest>({
    name: '',
    role: null,
    email: null,
    phone: null,
    department: null,
    is_primary: false,
  });

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!form.name.trim()) return;
    try {
      await mutation.mutateAsync({
        ...form,
        name: form.name.trim(),
        role: form.role?.trim() || null,
        email: form.email?.trim() || null,
        phone: form.phone?.trim() || null,
        department: form.department?.trim() || null,
      });
      toast.success('Contact added');
      onDone();
    } catch {
      toast.error('Could not add contact');
    }
  }

  const field = (key: 'role' | 'email' | 'phone' | 'department', label: string, type = 'text') => (
    <label className="block text-caption text-ink-3">
      {label}
      <Input
        type={type}
        className="mt-1"
        value={form[key] ?? ''}
        onChange={(event) => setForm((prev) => ({ ...prev, [key]: event.target.value }))}
      />
    </label>
  );

  return (
    <form onSubmit={submit} className="space-y-4">
      <label className="block text-caption text-ink-3">
        Name *
        <Input
          className="mt-1"
          value={form.name}
          onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
          required
        />
      </label>
      {field('role', 'Role / title')}
      {field('email', 'Email', 'email')}
      {field('phone', 'Phone')}
      {field('department', 'Department')}
      <label className="flex items-center gap-2 text-body text-ink-2">
        <input
          type="checkbox"
          checked={form.is_primary}
          onChange={(event) => setForm((prev) => ({ ...prev, is_primary: event.target.checked }))}
          className="h-4 w-4 rounded border-line-strong accent-accent-solid"
        />
        Make this the primary contact
      </label>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!form.name.trim()} loading={mutation.isPending}>
          Add contact
        </Button>
      </div>
    </form>
  );
}

function ContactsCard({
  customerId,
  contacts,
  loading,
  canAdd,
}: {
  customerId: string;
  contacts: ExporterContact[];
  loading: boolean;
  canAdd: boolean;
}) {
  const [adding, setAdding] = useState(false);
  return (
    <Card
      as="h3"
      title="Contacts"
      count={loading ? undefined : contacts.length}
      data-extension="contacts"
      actions={
        canAdd ? (
          <Button size="sm" variant="subtle" onClick={() => setAdding(true)}>
            <Icon.add size={16} aria-hidden />
            Add
          </Button>
        ) : undefined
      }
    >
      {adding && (
        <FormPanel title="Add a contact" onClose={() => setAdding(false)}>
          <AddContactForm customerId={customerId} onDone={() => setAdding(false)} />
        </FormPanel>
      )}
      {loading ? (
        <Loading />
      ) : contacts.length === 0 ? (
        <EmptyLine className="py-0">No one recorded yet.</EmptyLine>
      ) : (
        <List>
          {contacts.map((contact) => (
            <li key={contact.id} className="py-2" data-testid="person-tile">
              <div className="flex items-center gap-2">
                <p className="truncate text-body font-semibold text-ink">{contact.name}</p>
                {contact.is_primary_contact && <Badge variant="outline">Primary</Badge>}
              </div>
              <p className="truncate text-secondary text-ink-2">
                {[contact.role, contact.department].filter(Boolean).join(' · ') || 'No role added'}
              </p>
              {(contact.email || contact.phone) && (
                <p className="mt-0.5 flex flex-wrap gap-x-3 text-secondary">
                  {contact.email && (
                    <a href={`mailto:${contact.email}`} className="truncate text-accent hover:underline">
                      {contact.email}
                    </a>
                  )}
                  {contact.phone && (
                    <a href={`tel:${contact.phone}`} className="text-accent hover:underline">
                      {contact.phone}
                    </a>
                  )}
                </p>
              )}
            </li>
          ))}
        </List>
      )}
    </Card>
  );
}

function DocumentsCard({ customerId }: { customerId: string }) {
  const query = useCompanyDocuments(customerId, { limit: SHOWN });
  const documents = query.data?.documents ?? [];
  return (
    <Card
      as="h3"
      title="Documents"
      count={query.data?.total}
      footer={{ label: 'View all', to: paths.company(customerId, 'documents') }}
    >
      {query.isLoading ? (
        <Loading />
      ) : query.isError ? (
        <p className="text-secondary text-negative">Couldn&apos;t load documents.</p>
      ) : documents.length === 0 ? (
        <EmptyLine className="py-0">No documents yet.</EmptyLine>
      ) : (
        <List>
          {documents.map((document_) => (
            <Item
              key={document_.id}
              title={document_.file_name}
              detail={`${categoryLabel(document_.category)} · ${formatDateTime(document_.uploaded_at)}`}
              badge={<ScanStatusBadge status={document_.scan_status} />}
            />
          ))}
        </List>
      )}
    </Card>
  );
}

export function CompanyRelatedCards({
  customerId,
  contacts,
  contactsLoading,
  canAdd,
  className,
}: {
  customerId: string;
  contacts: ExporterContact[];
  contactsLoading: boolean;
  /** Staff may add a contact; Developer reads. */
  canAdd: boolean;
  className?: string;
}) {
  return (
    <aside aria-label="Related" className={className}>
      <div className="flex flex-col gap-4">
        <FollowUpsCard customerId={customerId} />
        <DealsCard customerId={customerId} />
        <ContactsCard customerId={customerId} contacts={contacts} loading={contactsLoading} canAdd={canAdd} />
        <DocumentsCard customerId={customerId} />
      </div>
    </aside>
  );
}
