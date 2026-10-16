/**
 * A company's directors and beneficial owners: its People.
 *
 * A person is one record with roles — a contact, a director, a beneficial owner, or
 * several — so a director who is also the main contact appears here and under Contacts
 * as the same person. Only the first name and a role are required. A DIN belongs to a
 * director, an ownership share and control type to an owner; date of birth, DIN and the
 * identification number arrive masked for a role that may not see them, and are typed
 * over, never edited in place (the same rule the contact form follows for email).
 *
 * Every director and owner is a subject of the sanctions screening; adding one puts the
 * company's screening on "never screened" for that person.
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
} from '@/components';
import { Icon } from '@/design/icons';
import { useCan } from '@/platform/access';

import { countryLabel } from '../countries';
import { useAddExporterContact, useCompanyPeople, useUpdateExporterContact } from '../hooks';
import type {
  AddExporterContactRequest,
  ExporterContact,
  UpdateExporterContactRequest,
} from '../types';

import { CountrySelect } from './CountrySelect';

const CONTROL_TYPE_LABEL = {
  DIRECT_OWNERSHIP: 'Direct ownership',
  INDIRECT_OWNERSHIP: 'Indirect ownership',
  VOTING_RIGHTS: 'Voting rights',
  OTHER_CONTROL: 'Other control',
} as const;
type ControlType = keyof typeof CONTROL_TYPE_LABEL;

const IDENTIFICATION_LABEL = {
  PASSPORT: 'Passport',
  NATIONAL_ID: 'National ID',
  DRIVING_LICENCE: 'Driving licence',
} as const;
type IdentificationType = keyof typeof IDENTIFICATION_LABEL;

interface PersonForm {
  first_name: string;
  last_name: string;
  is_director: boolean;
  is_ubo: boolean;
  is_contact: boolean;
  din: string;
  date_of_birth: string;
  nationality: string;
  residence_country: string;
  ownership_pct: string;
  control_type: ControlType | '';
  identification_type: IdentificationType | '';
  identification_number: string;
}

const EMPTY: PersonForm = {
  first_name: '',
  last_name: '',
  is_director: true,
  is_ubo: false,
  is_contact: false,
  din: '',
  date_of_birth: '',
  nationality: '',
  residence_country: '',
  ownership_pct: '',
  control_type: '',
  identification_type: '',
  identification_number: '',
};

const text = (value: string) => value.trim() || null;

/** Why the form cannot be sent yet, or null when it can. The server says the same. */
function problem(form: PersonForm, numberRequired: boolean): string | null {
  if (!form.first_name.trim()) return 'Give the person a first name.';
  if (!form.is_director && !form.is_ubo) return 'Choose director, beneficial owner, or both.';
  if (form.is_director && form.din.trim() && !/^[0-9]{8}$/.test(form.din.trim())) {
    return 'A DIN is eight digits.';
  }
  if (form.is_ubo && form.ownership_pct.trim()) {
    const share = Number(form.ownership_pct);
    if (Number.isNaN(share) || share < 0 || share > 100) return 'An ownership share is between 0 and 100.';
  }
  const hasNumber = Boolean(form.identification_number.trim());
  if (hasNumber && !form.identification_type) return 'Choose what the identification number is from.';
  if (numberRequired && form.identification_type && !hasNumber) {
    return 'Give the identification number, or clear its type.';
  }
  return null;
}

function PersonFields({
  form,
  setForm,
  hidden,
}: {
  form: PersonForm;
  setForm: React.Dispatch<React.SetStateAction<PersonForm>>;
  /** The masked fields start empty: typing replaces them. */
  hidden: boolean;
}) {
  const set = <K extends keyof PersonForm>(key: K, value: PersonForm[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const placeholder = hidden ? 'Hidden — type to replace' : undefined;
  const role = (key: 'is_director' | 'is_ubo' | 'is_contact', label: string) => (
    <label className="flex items-center gap-2 text-body text-ink-2">
      <input
        type="checkbox"
        checked={form[key]}
        onChange={(event) => set(key, event.target.checked)}
        className="h-4 w-4 rounded border-line-strong accent-accent-solid"
      />
      {label}
    </label>
  );
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <Field label="First name" htmlFor="person-first-name" required>
          <Input
            id="person-first-name"
            value={form.first_name}
            maxLength={120}
            onChange={(event) => set('first_name', event.target.value)}
          />
        </Field>
        <Field label="Last name" htmlFor="person-last-name">
          <Input
            id="person-last-name"
            value={form.last_name}
            maxLength={120}
            onChange={(event) => set('last_name', event.target.value)}
          />
        </Field>
      </div>
      <fieldset className="space-y-1.5">
        <legend className="text-caption font-medium text-ink-2">Roles</legend>
        {role('is_director', 'Director')}
        {role('is_ubo', 'Beneficial owner')}
        {role('is_contact', 'Also someone we talk to (listed under Contacts)')}
      </fieldset>
      {form.is_director && (
        <Field label="DIN (Director Identification Number)" htmlFor="person-din">
          <Input
            id="person-din"
            inputMode="numeric"
            value={form.din}
            placeholder={placeholder}
            onChange={(event) => set('din', event.target.value)}
          />
        </Field>
      )}
      {form.is_ubo && (
        <div className="grid grid-cols-2 gap-3">
          <Field label="Ownership %" htmlFor="person-share">
            <Input
              id="person-share"
              inputMode="decimal"
              value={form.ownership_pct}
              onChange={(event) => set('ownership_pct', event.target.value)}
            />
          </Field>
          <Field label="Control" htmlFor="person-control">
            <Select
              id="person-control"
              value={form.control_type}
              onChange={(event) => set('control_type', event.target.value as ControlType | '')}
            >
              <option value="">Not given</option>
              {(Object.keys(CONTROL_TYPE_LABEL) as ControlType[]).map((key) => (
                <option key={key} value={key}>
                  {CONTROL_TYPE_LABEL[key]}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      )}
      <Field label="Date of birth" htmlFor="person-birth">
        <Input
          id="person-birth"
          type="date"
          value={form.date_of_birth}
          onChange={(event) => set('date_of_birth', event.target.value)}
        />
        {hidden && <p className="mt-1 text-caption text-ink-3">Hidden — pick a date to replace it.</p>}
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Nationality" htmlFor="person-nationality">
          <CountrySelect
            id="person-nationality"
            value={form.nationality}
            onChange={(code) => set('nationality', code)}
            placeholder="Not given"
          />
        </Field>
        <Field label="Lives in" htmlFor="person-residence">
          <CountrySelect
            id="person-residence"
            value={form.residence_country}
            onChange={(code) => set('residence_country', code)}
            placeholder="Not given"
          />
        </Field>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Identification" htmlFor="person-id-type">
          <Select
            id="person-id-type"
            value={form.identification_type}
            onChange={(event) => set('identification_type', event.target.value as IdentificationType | '')}
          >
            <option value="">None</option>
            {(Object.keys(IDENTIFICATION_LABEL) as IdentificationType[]).map((key) => (
              <option key={key} value={key}>
                {IDENTIFICATION_LABEL[key]}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Number" htmlFor="person-id-number">
          <Input
            id="person-id-number"
            value={form.identification_number}
            placeholder={placeholder}
            onChange={(event) => set('identification_number', event.target.value)}
          />
        </Field>
      </div>
    </>
  );
}

function AddPersonForm({ customerId, onDone }: { customerId: string; onDone: () => void }) {
  const mutation = useAddExporterContact(customerId);
  const [form, setForm] = useState<PersonForm>(EMPTY);
  const blocked = problem(form, false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (blocked) return;
    const payload: AddExporterContactRequest = {
      first_name: form.first_name.trim(),
      last_name: text(form.last_name),
      role: null,
      email: null,
      phone: null,
      department: null,
      is_primary: false,
      is_contact: form.is_contact,
      is_director: form.is_director,
      is_ubo: form.is_ubo,
      din: form.is_director ? text(form.din) : null,
      date_of_birth: text(form.date_of_birth),
      nationality: text(form.nationality),
      residence_country: text(form.residence_country),
      ownership_pct: form.is_ubo ? text(form.ownership_pct) : null,
      control_type: form.is_ubo && form.control_type ? form.control_type : null,
      identification_type: form.identification_type || null,
      identification_number: text(form.identification_number),
    };
    try {
      await mutation.mutateAsync(payload);
      toast.success('Person added');
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not add the person');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <PersonFields form={form} setForm={setForm} hidden={false} />
      {blocked && form.first_name.trim() && <p className="text-secondary text-ink-3">{blocked}</p>}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={Boolean(blocked)} loading={mutation.isPending}>
          Add person
        </Button>
      </div>
    </form>
  );
}

/**
 * Change one person. Sends only what changed. A masked field (date of birth, DIN,
 * identification number) starts empty for a role that reads it masked and is sent only
 * when typed into, so the bullets never reach the record.
 */
function EditPersonForm({
  customerId,
  person,
  onDone,
}: {
  customerId: string;
  person: ExporterContact;
  onDone: () => void;
}) {
  const mutation = useUpdateExporterContact(customerId);
  const mayReveal = useCan('identifiers.reveal');
  const masked = (value: string | null | undefined) => (mayReveal ? (value ?? '') : '');
  const [form, setForm] = useState<PersonForm>({
    first_name: person.first_name,
    last_name: person.last_name ?? '',
    is_director: person.is_director,
    is_ubo: person.is_ubo,
    is_contact: person.is_contact,
    din: masked(person.din),
    date_of_birth: masked(person.date_of_birth),
    nationality: person.nationality ?? '',
    residence_country: person.residence_country ?? '',
    ownership_pct: person.ownership_pct != null ? String(person.ownership_pct) : '',
    control_type: (person.control_type as ControlType | null) ?? '',
    identification_type: (person.identification_type as IdentificationType | null) ?? '',
    identification_number: masked(person.identification_number),
  });
  // A masked number left empty is "unchanged", so a type alone is fine then.
  const blocked = problem(form, mayReveal);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (blocked) return;
    const payload: UpdateExporterContactRequest = {};
    if (form.first_name.trim() !== person.first_name) payload.first_name = form.first_name.trim();
    if (text(form.last_name) !== (person.last_name ?? null)) payload.last_name = text(form.last_name);
    if (form.is_director !== person.is_director) payload.is_director = form.is_director;
    if (form.is_ubo !== person.is_ubo) payload.is_ubo = form.is_ubo;
    if (form.is_contact !== person.is_contact) payload.is_contact = form.is_contact;
    const changedMasked = (value: string, current: string | null | undefined) =>
      mayReveal ? text(value) !== (current ?? null) : Boolean(value.trim());
    if (form.is_director && changedMasked(form.din, person.din)) payload.din = text(form.din);
    if (changedMasked(form.date_of_birth, person.date_of_birth)) {
      payload.date_of_birth = text(form.date_of_birth);
    }
    if (text(form.nationality) !== (person.nationality ?? null)) payload.nationality = text(form.nationality);
    if (text(form.residence_country) !== (person.residence_country ?? null)) {
      payload.residence_country = text(form.residence_country);
    }
    if (form.is_ubo) {
      const share = text(form.ownership_pct);
      const current = person.ownership_pct != null ? String(person.ownership_pct) : null;
      if (share !== current) payload.ownership_pct = share;
      if ((form.control_type || null) !== (person.control_type ?? null)) {
        payload.control_type = form.control_type || null;
      }
    }
    if ((form.identification_type || null) !== (person.identification_type ?? null)) {
      payload.identification_type = form.identification_type || null;
    }
    if (changedMasked(form.identification_number, person.identification_number)) {
      payload.identification_number = text(form.identification_number);
    }
    if (Object.keys(payload).length === 0) {
      onDone();
      return;
    }
    try {
      await mutation.mutateAsync({ contactId: person.id, payload });
      toast.success('Person updated');
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not update the person');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <PersonFields form={form} setForm={setForm} hidden={!mayReveal} />
      {blocked && <p className="text-secondary text-ink-3">{blocked}</p>}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={Boolean(blocked)} loading={mutation.isPending}>
          Save person
        </Button>
      </div>
    </form>
  );
}

function describe(person: ExporterContact): string {
  return [
    person.is_director && person.din ? `DIN ${person.din}` : null,
    person.is_ubo && person.ownership_pct != null ? `${Number(person.ownership_pct)}% owned` : null,
    person.nationality ? countryLabel(person.nationality) : null,
  ]
    .filter(Boolean)
    .join(' · ');
}

export function PeopleCard({ customerId, canAdd }: { customerId: string; canAdd: boolean }) {
  const query = useCompanyPeople(customerId);
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ExporterContact | null>(null);
  const people = (query.data?.contacts ?? []).filter((person) => person.is_director || person.is_ubo);
  const active = people.filter((person) => person.status === 'ACTIVE');
  return (
    <Card
      as="h3"
      title="Directors and owners"
      count={query.isLoading ? undefined : active.length}
      data-extension="people"
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
        <FormPanel title="Add a director or owner" onClose={() => setAdding(false)}>
          <AddPersonForm customerId={customerId} onDone={() => setAdding(false)} />
        </FormPanel>
      )}
      {editing && (
        <FormPanel title={`Edit ${editing.name}`} onClose={() => setEditing(null)}>
          <EditPersonForm customerId={customerId} person={editing} onDone={() => setEditing(null)} />
        </FormPanel>
      )}
      {query.isLoading ? (
        <Skeleton className="h-9" />
      ) : query.isError ? (
        <p className="text-secondary text-negative">Couldn&apos;t load directors and owners.</p>
      ) : people.length === 0 ? (
        <EmptyLine className="py-0">No directors or owners recorded.</EmptyLine>
      ) : (
        <ul className="-my-2 divide-y divide-line">
          {people.map((person) => (
            <li key={person.id} className="py-2" data-testid="people-tile">
              <div className="flex items-center gap-2">
                <p
                  className={
                    person.status === 'ACTIVE'
                      ? 'truncate text-body font-semibold text-ink'
                      : 'truncate text-body font-semibold text-ink-3'
                  }
                >
                  {person.name}
                </p>
                {person.is_director && <Badge variant="outline">Director</Badge>}
                {person.is_ubo && <Badge variant="outline">Owner</Badge>}
                {person.status !== 'ACTIVE' && (
                  <Badge tone="neutral">{person.status === 'LEFT_COMPANY' ? 'Left company' : 'Inactive'}</Badge>
                )}
                {canAdd && (
                  <button
                    type="button"
                    onClick={() => setEditing(person)}
                    aria-label={`Edit ${person.name}`}
                    className="ml-auto shrink-0 rounded p-1 text-ink-4 transition-colors duration-quick hover:bg-sunken hover:text-ink"
                  >
                    <Icon.edit size={14} aria-hidden />
                  </button>
                )}
              </div>
              {describe(person) && <p className="truncate text-secondary text-ink-2">{describe(person)}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
