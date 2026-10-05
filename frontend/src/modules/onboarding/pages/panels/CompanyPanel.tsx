/**
 * The profile chapter (frontend-plan §8.5): the company's facts as inline edits for
 * staff — click a fact, change it, Enter — and as plain text for everyone else. No
 * edit form. Each change is a one-field PATCH; the server's refusal stays under the
 * field in its words, and a duplicate PAN names its holder by link, never by id.
 *
 * The company record (architecture §8.1, §9.2).
 *
 * The company's own attributes: identity, identifiers, industry and
 * footprint, where it stands (journey, qualification, marker) and the
 * duplicate-GSTIN warnings. Staff can edit the profile here; the journey,
 * qualification and marker are not profile fields and are never sent — the
 * server refuses them on this route.
 *
 * The onboarding-history table that used to sit below the conversation panel
 * is gone. The company's name was taken from it; the name is now part
 * of the company's own identity, shown in the page header, and the legacy
 * onboarding path's records stay with that path.
 */

import { useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Editable } from '@/components';
import { Icon } from '@/design/icons';
import { formatDate, humanize } from '@/lib/format';
import { useCan } from '@/platform/access';
import { Identifier } from '@/platform/mask';

import { DuplicatePanMessage, duplicatePanHolder } from '../../components';
import { useUpdateExporterProfile } from '../../hooks';
import { paths } from '../../paths';
import type { ExporterProfileDetail, UpdateExporterProfileRequest } from '../../types';

type FieldKey =
  | 'name'
  | 'country'
  | 'pan'
  | 'iec'
  | 'cin'
  | 'registration_number'
  | 'relationship_manager'
  | 'industry'
  | 'export_markets'
  | 'products'
  | 'year_established';

const LIST_FIELDS = new Set<FieldKey>(['export_markets', 'products']);

/**
 * Identifiers a masked role is sent masked: editing one starts empty ("type to
 * replace"), so the bullets are never sent back as a value.
 */
const MASKED_FIELDS = new Set<FieldKey>(['pan', 'iec', 'cin', 'registration_number']);

function splitList(text: string): string[] {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * The one-field PATCH for an edit (the old form's rules, field by field): lists are
 * comma-separated; a year of digits is a number and anything else goes as typed, so
 * the server refuses it (never sent as a cleared year); an empty value clears.
 */
function patchFor(key: FieldKey, text: string): UpdateExporterProfileRequest {
  const value = text.trim();
  if (LIST_FIELDS.has(key)) {
    const items = splitList(value);
    return { [key]: items.length ? items : null } as UpdateExporterProfileRequest;
  }
  if (key === 'year_established') {
    return { year_established: value ? (/^\d+$/.test(value) ? Number(value) : value) : null } as UpdateExporterProfileRequest;
  }
  return { [key]: value || null } as UpdateExporterProfileRequest;
}

/** Shared GSTINs name the other companies by link, never by id. */
function OtherCompanies({ ids }: { ids: string[] }) {
  const link = (id: string, text: string) => (
    <Link to={paths.company(id)} className="text-ink underline">
      {text}
    </Link>
  );
  if (ids.length === 1) return link(ids[0]!, 'another company');
  return (
    <>
      {ids.length} other companies:{' '}
      {ids.map((id, i) => (
        <span key={id}>
          {i > 0 && (i === ids.length - 1 ? ' and ' : ', ')}
          {link(id, `company ${i + 1}`)}
        </span>
      ))}
    </>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 grid-cols-[9.5rem_1fr] items-baseline gap-4 border-b border-line py-2.5 last:border-b-0">
      <dt className="text-secondary text-ink-3">{label}</dt>
      <dd className="min-w-0 text-body text-ink">{children}</dd>
    </div>
  );
}

export function CompanyPanel({
  profile,
  canEdit = false,
}: {
  profile: ExporterProfileDetail;
  canEdit?: boolean;
}) {
  const mutation = useUpdateExporterProfile(profile.customer_id);
  const reveal = useCan('identifiers.reveal');
  // The company already holding a PAN just typed, shown as a link under the PAN.
  const [panHolder, setPanHolder] = useState<string | null>(null);

  const save = (key: FieldKey) => async (next: string) => {
    if (key === 'pan') setPanHolder(null);
    try {
      await mutation.mutateAsync(patchFor(key, next));
      toast.success('Profile updated');
    } catch (error) {
      const holder = key === 'pan' ? duplicatePanHolder(error) : null;
      if (holder) {
        setPanHolder(holder);
        throw new Error('This PAN is already held by another company.');
      }
      throw error;
    }
  };

  /** A fact staff may change in place; plain text for everyone else. */
  const editable = (key: FieldKey, label: string, value: string | null, display?: ReactNode) => {
    const masked = !reveal && MASKED_FIELDS.has(key);
    return (
      <Editable
        label={label}
        value={masked ? '' : value}
        display={display ?? value}
        onSave={save(key)}
        readOnly={!canEdit}
        inputPlaceholder={masked ? 'Hidden — type to replace' : undefined}
        // An identifier brings its own reveal and copy buttons, so only the pencil
        // opens the field.
        trigger={display ? 'pencil' : 'value'}
      />
    );
  };

  return (
    <div className="space-y-6">
      {profile.gstin_warnings.length > 0 && (
        <section
          role="alert"
          className="rounded-md border-l-2 border-attention-solid bg-attention-tint p-4 text-body text-ink"
        >
          <div className="flex items-center gap-2 font-medium">
            <Icon.warning size={15} className="text-attention" aria-hidden />A GSTIN on this company is also on another company
          </div>
          <ul className="mt-2 space-y-1">
            {profile.gstin_warnings.map((warning) => (
              <li key={warning.gstin}>
                <Identifier kind="GSTIN" value={warning.gstin} /> — also on{' '}
                <OtherCompanies ids={warning.other_customer_ids} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <section aria-labelledby="company-profile-heading">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="company-profile-heading" className="text-lead font-semibold text-ink">
            Company profile
          </h2>
          {canEdit && <p className="text-secondary text-ink-3">Click a fact to change it.</p>}
        </div>
        <div className="mt-2 grid gap-x-10 lg:grid-cols-2">
          <dl>
            <Fact label="Company name">{editable('name', 'Company name', profile.name)}</Fact>
            <Fact label="Country">{editable('country', 'Country', profile.country)}</Fact>
            <Fact label="PAN">
              {editable('pan', 'PAN', profile.pan, <Identifier kind="PAN" value={profile.pan} />)}
              {panHolder && (
                <div className="mt-1 text-secondary">
                  <DuplicatePanMessage holderId={panHolder} />
                </div>
              )}
            </Fact>
            <Fact label="IEC">{editable('iec', 'IEC', profile.iec, <Identifier kind="IEC" value={profile.iec} />)}</Fact>
            <Fact label="CIN">{editable('cin', 'CIN', profile.cin, <Identifier kind="CIN" value={profile.cin} />)}</Fact>
            <Fact label="Registration number">
              {editable(
                'registration_number',
                'Registration number',
                profile.registration_number,
                <Identifier value={profile.registration_number} />,
              )}
            </Fact>
            {/* The GSTINs themselves are the branches below; the count
                stays, because "how many states" belongs in the summary. */}
            <Fact label="GST registrations">
              {profile.gstins.length === 0
                ? 'None'
                : profile.gstins.length === 1
                  ? '1 active'
                  : `${profile.gstins.length} active`}
            </Fact>
          </dl>
          <dl>
            <Fact label="Industry">{editable('industry', 'Industry', profile.industry)}</Fact>
            <Fact label="Export markets">
              {editable(
                'export_markets',
                'Export markets',
                profile.export_markets?.length ? profile.export_markets.join(', ') : null,
              )}
            </Fact>
            <Fact label="Products">
              {editable('products', 'Products', profile.products?.length ? profile.products.join(', ') : null)}
            </Fact>
            <Fact label="Year established">
              {editable('year_established', 'Year established', profile.year_established?.toString() ?? null)}
            </Fact>
            <Fact label="Owner">{editable('relationship_manager', 'Owner', profile.relationship_manager)}</Fact>
            <Fact label="Source">{humanize(profile.source)}</Fact>
            <Fact label="Created">{formatDate(profile.created_at)}</Fact>
            <Fact label="Last updated">{formatDate(profile.updated_at)}</Fact>
          </dl>
        </div>
      </section>
    </div>
  );
}
