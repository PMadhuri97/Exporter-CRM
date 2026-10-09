/**
 * Settings → Sanctions lists: which lists a screening covers.
 *
 * Each list has a code, a name, the authority that issues it, whether it is active and
 * whether it is **mandatory** (every screening must cover it), and the date of the
 * published version screenings use. **Recording a newer version date** puts every
 * company screened against an older one on *Re-screen due*. Every change writes a new
 * version, so a past screening keeps the list version it used.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Badge,
  Button,
  Card,
  ErrorState,
  Field,
  FormPanel,
  Input,
  PageHeader,
  RequiredNote,
  Skeleton,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import { useAddSanctionsList, useReviseSanctionsList, useSanctionsLists } from '../hooks';
import type { SanctionsList } from '../types';

function ListForm({ editing, onDone }: { editing?: SanctionsList; onDone: () => void }) {
  const add = useAddSanctionsList();
  const revise = useReviseSanctionsList();
  const [code, setCode] = useState(editing?.code ?? '');
  const [name, setName] = useState(editing?.name ?? '');
  const [authority, setAuthority] = useState(editing?.authority ?? '');
  const [mandatory, setMandatory] = useState(editing?.mandatory ?? false);
  const [versionDate, setVersionDate] = useState(editing?.list_version_date ?? '');
  const ready = code.trim() && name.trim() && versionDate;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    try {
      if (editing) {
        await revise.mutateAsync({
          code: editing.code,
          body: {
            name: name.trim(),
            authority: authority.trim() || null,
            mandatory,
            list_version_date: versionDate,
          },
        });
        toast.success(
          versionDate !== editing.list_version_date
            ? 'New list version recorded — screened companies are now due a re-screen'
            : 'List changed',
        );
      } else {
        await add.mutateAsync({
          code: code.trim().toUpperCase(),
          name: name.trim(),
          authority: authority.trim() || null,
          mandatory,
          list_version_date: versionDate,
        });
        toast.success('Sanctions list added');
      }
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the list');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <Field label="Code" htmlFor="list-code" required hint="Letters, digits and _; it never changes.">
        <Input id="list-code" value={code} disabled={Boolean(editing)} onChange={(e) => setCode(e.target.value)} />
      </Field>
      <Field label="Name" htmlFor="list-name" required>
        <Input id="list-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. OFAC SDN List" />
      </Field>
      <Field label="Issuing authority" htmlFor="list-authority">
        <Input id="list-authority" value={authority} onChange={(e) => setAuthority(e.target.value)} />
      </Field>
      <Field
        label="Version date"
        htmlFor="list-version"
        required
        hint="The date of the published list screenings use. A newer date puts screened companies on Re-screen due."
      >
        <Input id="list-version" type="date" value={versionDate} onChange={(e) => setVersionDate(e.target.value)} />
      </Field>
      <label className="flex items-center gap-2 text-body text-ink-2">
        <input
          type="checkbox"
          checked={mandatory}
          onChange={(event) => setMandatory(event.target.checked)}
          className="h-4 w-4 rounded border-line-strong accent-accent-solid"
        />
        Mandatory — every screening must cover it
      </label>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={add.isPending || revise.isPending}>
          Save list
        </Button>
      </div>
    </form>
  );
}

export function SanctionsListsPage() {
  const query = useSanctionsLists();
  const revise = useReviseSanctionsList();
  const [form, setForm] = useState<{ editing?: SanctionsList } | null>(null);
  const lists = query.data?.lists ?? [];
  const canEdit = query.data?.can_edit ?? false;

  async function setActive(list: SanctionsList, active: boolean) {
    try {
      await revise.mutateAsync({ code: list.code, body: { active } });
      toast.success(active ? 'List in use again' : 'List no longer in use');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not change the list');
    }
  }

  return (
    <div className="max-w-reading">
      <PageHeader
        as="h2"
        title="Sanctions lists"
        actions={
          canEdit && (
            <Button variant="primary" onClick={() => setForm({})}>
              <Icon.add size={15} aria-hidden />
              Add a list
            </Button>
          )
        }
      />
      {form && (
        <FormPanel title={form.editing ? `Change ${form.editing.name}` : 'Add a sanctions list'} onClose={() => setForm(null)}>
          <ListForm editing={form.editing} onDone={() => setForm(null)} />
        </FormPanel>
      )}
      {query.isError ? (
        <ErrorState title="Couldn't load the sanctions lists." onRetry={() => void query.refetch()} />
      ) : query.isLoading ? (
        <div className="space-y-2" aria-hidden>
          <Skeleton className="h-12" />
          <Skeleton className="h-12" />
        </div>
      ) : (
        <Card title="Lists" as="h3" flush>
          <ul className="divide-y divide-line">
            {lists.map((list) => (
              <li key={list.id} data-testid="sanctions-list-row" className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className={list.active ? 'font-medium text-ink' : 'font-medium text-ink-3'}>{list.name}</span>
                    {list.mandatory && <Badge variant="outline">Mandatory</Badge>}
                    {!list.active && <Badge tone="neutral">Not in use</Badge>}
                  </p>
                  <p className="text-caption text-ink-3">
                    {list.authority ? `${list.authority} · ` : ''}version {formatDate(list.list_version_date)} ·{' '}
                    {list.code}
                  </p>
                </div>
                {canEdit && (
                  <div className="flex gap-2">
                    <Button size="sm" variant="subtle" onClick={() => setForm({ editing: list })}>
                      <Icon.edit size={14} /> Change
                    </Button>
                    <Button size="sm" variant="subtle" disabled={revise.isPending} onClick={() => void setActive(list, !list.active)}>
                      {list.active ? 'Stop using' : 'Use again'}
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
