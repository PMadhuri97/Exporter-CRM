/**
 * A company's addresses: registered, billing, shipping, factory or warehouse, and
 * correspondence — any number of each, with one default per type.
 *
 * * **Add and edit in one form.** Country is chosen by name and stored as its code.
 * * **Default per type.** The first address of a type is its default; *Make default*
 *   moves it. The server demotes the old default in the same write.
 * * **Deactivate, never delete.** A GST branch or an old document may name the
 *   address, so a deactivated one stays, greyed, behind *Show deactivated*.
 * * **From a GST registration.** A branch's portal address is free text; *Create
 *   address* fills the form from it (line, state, India) and links the new address to
 *   that branch.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Badge,
  Button,
  EmptySection,
  Field,
  FormPanel,
  Input,
  Panel,
  RequiredNote,
  Select,
  Skeleton,
} from '@/components';
import { Icon } from '@/design/icons';

import {
  useAddCompanyAddress,
  useCompanyAddresses,
  useDeactivateCompanyAddress,
  useGstRegistrations,
  useSetDefaultCompanyAddress,
  useUpdateCompanyAddress,
} from '../hooks';
import type { CompanyAddress, CompanyAddressType, UpdateCompanyAddressRequest } from '../types';

import { ADDRESS_TYPE_LABEL, addressLine } from './address-labels';
import { CountrySelect } from './CountrySelect';

const TYPES = Object.keys(ADDRESS_TYPE_LABEL) as CompanyAddressType[];

interface FormValues {
  address_type: CompanyAddressType;
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
  is_default: boolean;
}

const EMPTY: FormValues = {
  address_type: 'REGISTERED',
  line1: '',
  line2: '',
  city: '',
  state: '',
  postal_code: '',
  country: 'IN',
  is_default: false,
};

function fromAddress(address: CompanyAddress): FormValues {
  return {
    address_type: address.address_type,
    line1: address.line1,
    line2: address.line2 ?? '',
    city: address.city,
    state: address.state ?? '',
    postal_code: address.postal_code ?? '',
    country: address.country,
    is_default: address.is_default,
  };
}

function AddressForm({
  customerId,
  editing,
  initial,
  gstRegistrationId,
  onDone,
}: {
  customerId: string;
  /** The address being edited; absent when adding. */
  editing?: CompanyAddress;
  initial: FormValues;
  /** Link the new address to this GST registration. */
  gstRegistrationId?: string;
  onDone: () => void;
}) {
  const add = useAddCompanyAddress(customerId);
  const update = useUpdateCompanyAddress(customerId);
  const [form, setForm] = useState<FormValues>(initial);
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));
  const ready = Boolean(form.line1.trim() && form.city.trim() && form.country);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const text = (value: string) => value.trim() || null;
    try {
      if (editing) {
        const body: UpdateCompanyAddressRequest = {};
        const before = fromAddress(editing);
        if (form.address_type !== before.address_type) body.address_type = form.address_type;
        if (form.line1.trim() !== before.line1) body.line1 = form.line1.trim();
        if (text(form.line2) !== text(before.line2)) body.line2 = text(form.line2);
        if (form.city.trim() !== before.city) body.city = form.city.trim();
        if (text(form.state) !== text(before.state)) body.state = text(form.state);
        if (text(form.postal_code) !== text(before.postal_code)) {
          body.postal_code = text(form.postal_code);
        }
        if (form.country !== before.country) body.country = form.country;
        if (Object.keys(body).length > 0) {
          await update.mutateAsync({ addressId: editing.id, body });
          toast.success('Address updated');
        }
      } else {
        await add.mutateAsync({
          address_type: form.address_type,
          line1: form.line1.trim(),
          line2: text(form.line2),
          city: form.city.trim(),
          state: text(form.state),
          postal_code: text(form.postal_code),
          country: form.country,
          is_default: form.is_default,
          gst_registration_id: gstRegistrationId ?? null,
        });
        toast.success('Address added');
      }
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not save the address');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <Field label="Type" htmlFor="address-type" required>
        <Select
          id="address-type"
          value={form.address_type}
          onChange={(event) => set('address_type', event.target.value as CompanyAddressType)}
        >
          {TYPES.map((type) => (
            <option key={type} value={type}>
              {ADDRESS_TYPE_LABEL[type]}
            </option>
          ))}
        </Select>
      </Field>
      <Field label="Address line 1" htmlFor="address-line1" required>
        <Input id="address-line1" value={form.line1} onChange={(e) => set('line1', e.target.value)} />
      </Field>
      <Field label="Address line 2" htmlFor="address-line2">
        <Input id="address-line2" value={form.line2} onChange={(e) => set('line2', e.target.value)} />
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="City" htmlFor="address-city" required>
          <Input id="address-city" value={form.city} onChange={(e) => set('city', e.target.value)} />
        </Field>
        <Field label="State / region" htmlFor="address-state">
          <Input id="address-state" value={form.state} onChange={(e) => set('state', e.target.value)} />
        </Field>
        <Field label="Postal code" htmlFor="address-postal">
          <Input
            id="address-postal"
            value={form.postal_code}
            onChange={(e) => set('postal_code', e.target.value)}
          />
        </Field>
        <Field label="Country" htmlFor="address-country" required>
          <CountrySelect id="address-country" value={form.country} onChange={(code) => set('country', code)} />
        </Field>
      </div>
      {!editing && (
        <label className="flex items-center gap-2 text-body text-ink-2">
          <input
            type="checkbox"
            checked={form.is_default}
            onChange={(event) => set('is_default', event.target.checked)}
            className="h-4 w-4 rounded border-line-strong accent-accent-solid"
          />
          Make this the default {ADDRESS_TYPE_LABEL[form.address_type].toLowerCase()} address
        </label>
      )}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={add.isPending || update.isPending}>
          Save address
        </Button>
      </div>
    </form>
  );
}

export interface AddressesSectionProps {
  customerId: string;
  canEdit: boolean;
}

export function AddressesSection({ customerId, canEdit }: AddressesSectionProps) {
  const query = useCompanyAddresses(customerId);
  const branches = useGstRegistrations(canEdit ? customerId : undefined);
  const setDefault = useSetDefaultCompanyAddress(customerId);
  const deactivate = useDeactivateCompanyAddress(customerId);
  const [form, setForm] = useState<
    { editing?: CompanyAddress; initial: FormValues; gstRegistrationId?: string } | null
  >(null);
  const [showInactive, setShowInactive] = useState(false);

  const addresses = query.data?.addresses ?? [];
  const inactive = addresses.filter((address) => !address.is_active);
  const shown = showInactive ? addresses : addresses.filter((address) => address.is_active);
  // A branch with a portal address that no company address stands for yet.
  const unlinkedBranches = (branches.data?.registrations ?? []).filter(
    (branch) => branch.active && branch.address && !branch.address_id,
  );

  return (
    <Panel
      title="Addresses"
      actions={
        canEdit && (
          <Button size="sm" onClick={() => setForm({ initial: EMPTY })}>
            <Icon.add size={14} /> Add address
          </Button>
        )
      }
    >
      {form && (
        <FormPanel
          title={form.editing ? 'Edit address' : 'Add an address'}
          onClose={() => setForm(null)}
        >
          <AddressForm
            customerId={customerId}
            editing={form.editing}
            initial={form.initial}
            gstRegistrationId={form.gstRegistrationId}
            onDone={() => setForm(null)}
          />
        </FormPanel>
      )}

      {query.data?.registered_changed_since_clear && (
        <div
          role="status"
          className="mb-3 flex items-center gap-2 rounded-lg border border-attention/40 bg-attention-tint p-3 text-body text-ink"
        >
          <Icon.warning size={15} className="shrink-0 text-attention" aria-hidden />
          The registered address changed since the last Clear.
        </div>
      )}

      {canEdit && unlinkedBranches.length > 0 && (
        <ul className="mb-3 space-y-1">
          {unlinkedBranches.map((branch) => (
            <li key={branch.id} className="flex flex-wrap items-center gap-2 text-secondary text-ink-2">
              <span>
                GST branch {branch.state_name ?? branch.state_code}: {branch.address}
              </span>
              <Button
                size="sm"
                variant="subtle"
                onClick={() =>
                  setForm({
                    initial: {
                      ...EMPTY,
                      address_type: addresses.some((a) => a.is_active && a.address_type === 'REGISTERED')
                        ? 'BILLING'
                        : 'REGISTERED',
                      line1: (branch.address ?? '').slice(0, 255),
                      state: branch.state_name ?? '',
                    },
                    gstRegistrationId: branch.id,
                  })
                }
              >
                Create address
              </Button>
            </li>
          ))}
        </ul>
      )}

      {query.isLoading ? (
        <Skeleton className="h-20 rounded-lg" />
      ) : addresses.length === 0 ? (
        <EmptySection>No addresses recorded.</EmptySection>
      ) : (
        <>
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
            {shown.map((address) => (
              <li
                key={address.id}
                data-testid="address-row"
                className={`flex flex-wrap items-start justify-between gap-3 px-4 py-3 ${address.is_active ? '' : 'bg-paper'}`}
              >
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2">
                    <span className="font-medium text-ink">{ADDRESS_TYPE_LABEL[address.address_type]}</span>
                    {address.is_default && <Badge variant="outline">Default</Badge>}
                    {!address.is_active && <Badge tone="neutral">Deactivated</Badge>}
                  </p>
                  <p className="mt-0.5 text-body text-ink-2">{addressLine(address)}</p>
                </div>
                {canEdit && address.is_active && (
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {!address.is_default && (
                      <Button
                        size="sm"
                        variant="subtle"
                        disabled={setDefault.isPending}
                        onClick={() =>
                          setDefault.mutate(address.id, {
                            onSuccess: () => toast.success('Default address changed'),
                          })
                        }
                      >
                        Make default
                      </Button>
                    )}
                    <Button
                      size="sm"
                      variant="subtle"
                      onClick={() => setForm({ editing: address, initial: fromAddress(address) })}
                      aria-label={`Edit ${ADDRESS_TYPE_LABEL[address.address_type]} address`}
                    >
                      <Icon.edit size={14} /> Edit
                    </Button>
                    <Button
                      size="sm"
                      variant="subtle"
                      disabled={deactivate.isPending}
                      onClick={() =>
                        deactivate.mutate(
                          { addressId: address.id, reason: null },
                          { onSuccess: () => toast.success('Address deactivated') },
                        )
                      }
                    >
                      Deactivate
                    </Button>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {inactive.length > 0 && (
            <button
              type="button"
              onClick={() => setShowInactive((value) => !value)}
              className="mt-2 text-secondary text-accent hover:underline"
            >
              {showInactive ? 'Hide deactivated' : `Show deactivated (${inactive.length})`}
            </button>
          )}
        </>
      )}
    </Panel>
  );
}
