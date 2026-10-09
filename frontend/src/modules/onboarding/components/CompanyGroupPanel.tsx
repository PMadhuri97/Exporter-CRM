/**
 * The Group tab: the tree a company belongs to, from its ultimate parent down.
 *
 * Each member shows its stage, its background check and risk (for a reader of
 * compliance work; the server leaves them out for anyone else), its open deals and
 * their value. Staff may put this company under a parent — choosing the parent and how
 * they are related — or take it out of its group; a link that would make a loop is
 * refused by the server, in words. **Possible members** are companies that record the
 * same beneficial owner; they are only listed, never linked for you.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Badge, Button, EmptyLine, Field, FormPanel, Panel, Select, Skeleton } from '@/components';
import { Icon } from '@/design/icons';

import { JOURNEY_LABEL } from '../constants';
import { useCompanyGroup, useGroupSuggestions, useSetParentCompany } from '../hooks';
import { paths } from '../paths';
import type {
  BackgroundCheckRisk,
  BackgroundCheckState,
  ExporterJourney,
  GroupMember,
  SetParentCompanyRequest,
} from '../types';

import { CompanyPicker } from './CompanyPicker';
import { GROUP_RELATIONSHIP_LABEL } from './group-labels';
import { moneyLabel } from './payment-term-labels';
import { BackgroundCheckBadge } from './StatusBadge';

type Relationship = NonNullable<SetParentCompanyRequest['relationship']>;

function LinkParentForm({ customerId, onDone }: { customerId: string; onDone: () => void }) {
  const link = useSetParentCompany(customerId);
  const [parent, setParent] = useState<string | null>(null);
  const [relationship, setRelationship] = useState<Relationship>('SUBSIDIARY');

  async function save() {
    if (!parent) return;
    try {
      await link.mutateAsync({ parent_company_id: parent, relationship });
      toast.success('Linked to its parent');
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not link the companies');
    }
  }

  return (
    <div className="space-y-4">
      {parent ? (
        <p className="text-body text-ink">
          Parent chosen.{' '}
          <button type="button" className="text-accent hover:underline" onClick={() => setParent(null)}>
            Choose another
          </button>
        </p>
      ) : (
        <CompanyPicker onSelect={setParent} excludeCompanyId={customerId} />
      )}
      <Field label="How they are related" htmlFor="group-relationship" required>
        <Select
          id="group-relationship"
          value={relationship}
          onChange={(event) => setRelationship(event.target.value as Relationship)}
        >
          {(Object.keys(GROUP_RELATIONSHIP_LABEL) as Relationship[]).map((value) => (
            <option key={value} value={value}>
              {GROUP_RELATIONSHIP_LABEL[value]}
            </option>
          ))}
        </Select>
      </Field>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button variant="primary" disabled={!parent} loading={link.isPending} onClick={() => void save()}>
          Link
        </Button>
      </div>
    </div>
  );
}

function MemberRow({ member, current }: { member: GroupMember; current: boolean }) {
  const value = Object.entries(member.open_deal_value)
    .map(([currency, amount]) => moneyLabel(amount, currency))
    .join(', ');
  return (
    <li
      data-testid="group-member"
      className="flex flex-wrap items-center justify-between gap-3 py-2.5"
      style={{ paddingLeft: `${member.depth * 1.25}rem` }}
    >
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-2">
          {member.depth > 0 && <span aria-hidden className="text-ink-4">└</span>}
          {current ? (
            <span className="font-semibold text-ink">{member.name ?? 'Unnamed company'}</span>
          ) : (
            <Link to={paths.company(member.company_id)} className="font-semibold text-accent hover:underline">
              {member.name ?? 'Unnamed company'}
            </Link>
          )}
          {member.group_relationship && (
            <Badge variant="outline">{GROUP_RELATIONSHIP_LABEL[member.group_relationship]}</Badge>
          )}
          {member.depth === 0 && <Badge variant="outline">Ultimate parent</Badge>}
        </p>
        <p className="mt-0.5 text-caption text-ink-3">
          {JOURNEY_LABEL[member.journey as ExporterJourney] ?? member.journey} ·{' '}
          {member.open_deals === 1 ? '1 open deal' : `${member.open_deals} open deals`}
          {value ? ` · ${value}` : ''}
        </p>
      </div>
      {member.background_check && (
        <BackgroundCheckBadge
          state={member.background_check as BackgroundCheckState}
          risk={member.risk_rating as BackgroundCheckRisk | null}
        />
      )}
    </li>
  );
}

export function CompanyGroupPanel({
  customerId,
  canEdit,
  canSeeSuggestions,
}: {
  customerId: string;
  canEdit: boolean;
  canSeeSuggestions: boolean;
}) {
  const group = useCompanyGroup(customerId);
  const suggestions = useGroupSuggestions(customerId, canSeeSuggestions);
  const unlink = useSetParentCompany(customerId);
  const [linking, setLinking] = useState(false);
  const members = group.data?.members ?? [];
  const me = members.find((member) => member.company_id === customerId);

  async function leave() {
    try {
      await unlink.mutateAsync({ parent_company_id: null, relationship: null });
      toast.success('Taken out of the group');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not unlink the company');
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Panel
        title="Group"
        actions={
          canEdit && (
            <div className="flex gap-2">
              {me?.parent_company_id && (
                <Button size="sm" variant="subtle" disabled={unlink.isPending} onClick={() => void leave()}>
                  Remove from group
                </Button>
              )}
              <Button size="sm" onClick={() => setLinking(true)}>
                <Icon.add size={14} /> {me?.parent_company_id ? 'Change parent' : 'Set parent'}
              </Button>
            </div>
          )
        }
      >
        {linking && (
          <FormPanel title="Put this company under a parent" onClose={() => setLinking(false)}>
            <LinkParentForm customerId={customerId} onDone={() => setLinking(false)} />
          </FormPanel>
        )}
        {group.isLoading ? (
          <Skeleton className="h-24 rounded-lg" />
        ) : members.length <= 1 ? (
          <EmptyLine className="py-0">This company is not part of a group.</EmptyLine>
        ) : (
          <ul className="divide-y divide-line">
            {members.map((member) => (
              <MemberRow key={member.company_id} member={member} current={member.company_id === customerId} />
            ))}
          </ul>
        )}
      </Panel>
      {canSeeSuggestions && (suggestions.data?.suggestions.length ?? 0) > 0 && (
        <Panel title="Possible group members">
          <p className="mb-2 text-caption text-ink-3">
            These companies record the same beneficial owner. Nothing is linked until someone links it.
          </p>
          <ul className="space-y-1.5">
            {suggestions.data!.suggestions.map((suggestion) => (
              <li key={suggestion.company_id} className="text-body">
                <Link to={paths.company(suggestion.company_id, 'group')} className="text-accent hover:underline">
                  {suggestion.name ?? 'Unnamed company'}
                </Link>
                <span className="text-ink-3"> · shares {suggestion.shared_people.join(', ')}</span>
              </li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}
