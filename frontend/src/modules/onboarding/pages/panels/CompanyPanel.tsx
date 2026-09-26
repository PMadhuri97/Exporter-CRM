/**
 * The company record — **owner: Developer 2** (architecture §8.1, §9.2).
 *
 * The company's own attributes: identity, identifiers, industry and
 * footprint, where it stands (journey, qualification, marker) and the
 * duplicate-GSTIN warnings. Staff can edit the profile here; the journey,
 * qualification and marker are not profile fields and are never sent — the
 * server refuses them on this route.
 *
 * The onboarding-history table that used to sit below the conversation panel
 * is gone (L2-03). The company's name was taken from it; the name is now part
 * of the company's own identity, shown in the page header, and the legacy
 * onboarding path's records stay with that path.
 */

import { AlertTriangle, ExternalLink } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { DetailRow } from '@/components';
import { formatDate, humanize } from '@/lib/format';
import { useCurrentUser } from '@/platform/auth';
import { MaskedValue, canReveal } from '@/platform/mask';

import { JourneyChip, MarkerBadge, QualificationChip } from '../../components';
import { useUpdateExporterProfile } from '../../hooks';
import type { ExporterProfileDetail, UpdateExporterProfileRequest } from '../../types';

/** The editable fields, as the form holds them (lists as comma-separated text). */
interface ProfileDraft {
  name: string;
  country: string;
  pan: string;
  gstins: string;
  iec: string;
  cin: string;
  relationship_manager: string;
  industry: string;
  export_markets: string;
  products: string;
  year_established: string;
  website: string;
}

const FIELDS: { key: keyof ProfileDraft; label: string }[] = [
  { key: 'name', label: 'Company name' },
  { key: 'country', label: 'Country' },
  { key: 'pan', label: 'PAN' },
  { key: 'gstins', label: 'GSTINs (comma-separated)' },
  { key: 'iec', label: 'IEC' },
  { key: 'cin', label: 'CIN' },
  { key: 'relationship_manager', label: 'Owner' },
  { key: 'industry', label: 'Industry' },
  { key: 'export_markets', label: 'Export markets (comma-separated)' },
  { key: 'products', label: 'Products (comma-separated)' },
  { key: 'year_established', label: 'Year established' },
  { key: 'website', label: 'Website' },
];

const LIST_FIELDS = new Set<keyof ProfileDraft>(['gstins', 'export_markets', 'products']);

/** Identifiers masked for roles that may not reveal them. */
const MASKED_FIELDS = new Set<keyof ProfileDraft>(['pan', 'gstins', 'iec']);

/**
 * A role that may not reveal identifiers (OPERATIONS) can still edit, so its
 * form starts those fields empty rather than putting the unmasked value in an
 * input: left empty they are unchanged, and typed they replace the old value.
 */
function draftFrom(profile: ExporterProfileDetail, revealIdentifiers: boolean): ProfileDraft {
  return {
    name: profile.name ?? '',
    country: profile.country ?? '',
    pan: revealIdentifiers ? (profile.pan ?? '') : '',
    gstins: revealIdentifiers ? profile.gstins.join(', ') : '',
    iec: revealIdentifiers ? (profile.iec ?? '') : '',
    cin: profile.cin ?? '',
    relationship_manager: profile.relationship_manager ?? '',
    industry: profile.industry ?? '',
    export_markets: (profile.export_markets ?? []).join(', '),
    products: (profile.products ?? []).join(', '),
    year_established: profile.year_established?.toString() ?? '',
    website: profile.website ?? '',
  };
}

function splitList(text: string): string[] {
  return text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

/**
 * Only the fields the user changed are sent — the PATCH touches exactly
 * those — and a field emptied is sent as `null`, which clears it. Validation
 * (PAN/GSTIN formats, name and country together) is the server's.
 */
function changesBetween(
  before: ProfileDraft,
  after: ProfileDraft,
): UpdateExporterProfileRequest {
  const changes: Record<string, unknown> = {};
  for (const { key } of FIELDS) {
    if (before[key] === after[key]) continue;
    const text = after[key].trim();
    if (LIST_FIELDS.has(key)) {
      const items = splitList(text);
      changes[key] = items.length ? items : null;
    } else if (key === 'year_established') {
      changes[key] = text ? Number(text) : null;
    } else {
      changes[key] = text || null;
    }
  }
  return changes as UpdateExporterProfileRequest;
}

function ProfileEditForm({
  profile,
  onDone,
}: {
  profile: ExporterProfileDetail;
  onDone: () => void;
}) {
  const mutation = useUpdateExporterProfile(profile.customer_id);
  const { role } = useCurrentUser();
  const reveal = canReveal(role);
  const [initial] = useState(() => draftFrom(profile, reveal));
  const [draft, setDraft] = useState(initial);
  const changes = changesBetween(initial, draft);
  const changed = Object.keys(changes).length > 0;

  return (
    <form
      aria-label="Edit profile"
      className="mt-3 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        mutation.mutate(changes, {
          onSuccess: () => {
            toast.success('Profile updated');
            onDone();
          },
          onError: (error) => toast.error(error.message),
        });
      }}
    >
      <div className="grid gap-3 md:grid-cols-2">
        {FIELDS.map(({ key, label }) => (
          <label key={key} className="flex flex-col gap-1 text-sm text-ink-muted">
            {label}
            <input
              className="input"
              placeholder={!reveal && MASKED_FIELDS.has(key) ? 'Hidden — type to replace' : undefined}
              inputMode={key === 'year_established' ? 'numeric' : undefined}
              value={draft[key]}
              onChange={(e) => setDraft((current) => ({ ...current, [key]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={onDone}
          className="rounded-lg px-3 py-1.5 text-sm text-ink-muted hover:bg-surface-sunken"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={!changed || mutation.isPending}
          className="rounded-lg bg-ink px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
        >
          Save profile
        </button>
      </div>
    </form>
  );
}

export function CompanyPanel({
  profile,
  canEdit = false,
}: {
  profile: ExporterProfileDetail;
  canEdit?: boolean;
}) {
  const [editing, setEditing] = useState(false);

  return (
    <div className="space-y-5">
      {profile.gstin_warnings.length > 0 && (
        <section
          role="alert"
          className="rounded-lg border border-status-pending/40 bg-status-pending/10 p-4 text-sm text-ink"
        >
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle size={15} className="text-status-pending" />
            A GSTIN on this company is also on another company
          </div>
          <ul className="mt-2 space-y-1">
            {profile.gstin_warnings.map((warning) => (
              <li key={warning.gstin}>
                <MaskedValue value={warning.gstin} /> — also on{' '}
                {warning.other_customer_ids.map((id, i) => (
                  <span key={id}>
                    {i > 0 && ', '}
                    <Link to={`/exporters/${id}`} className="text-brand-600 underline">
                      another company
                    </Link>
                  </span>
                ))}
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-ink">Exporter profile</h2>
            {canEdit && !editing && (
              <button
                type="button"
                onClick={() => setEditing(true)}
                className="rounded-lg border border-border px-3 py-1 text-sm font-medium text-ink hover:bg-surface-subtle"
              >
                Edit profile
              </button>
            )}
          </div>
          {editing ? (
            <ProfileEditForm profile={profile} onDone={() => setEditing(false)} />
          ) : (
            <dl className="mt-2">
              <DetailRow label="Country">{profile.country ?? '—'}</DetailRow>
              <DetailRow label="PAN"><MaskedValue value={profile.pan} /></DetailRow>
              <DetailRow label={profile.gstins.length > 1 ? 'GSTINs' : 'GSTIN'}>
                {profile.gstins.length === 0 ? '—' : (
                  <span className="flex flex-col items-end">
                    {profile.gstins.map((gstin) => <MaskedValue key={gstin} value={gstin} />)}
                  </span>
                )}
              </DetailRow>
              <DetailRow label="IEC"><MaskedValue value={profile.iec} /></DetailRow>
              <DetailRow label="CIN">{profile.cin ?? '—'}</DetailRow>
              <DetailRow label="Source">{humanize(profile.source)}</DetailRow>
              <DetailRow label="Industry">{profile.industry ?? '—'}</DetailRow>
              <DetailRow label="Established">{profile.year_established ?? '—'}</DetailRow>
              <DetailRow label="Website">
                {profile.website ? (
                  <a href={profile.website} target="_blank" rel="noreferrer" className="inline-flex max-w-full items-center gap-1 text-brand-600 hover:underline">
                    <span className="truncate">{profile.website}</span><ExternalLink size={13} className="shrink-0" />
                  </a>
                ) : '—'}
              </DetailRow>
            </dl>
          )}
        </section>

        <div className="space-y-5">
          <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
            <h2 className="font-semibold text-ink">Where it stands</h2>
            <dl className="mt-2">
              <DetailRow label="Journey"><JourneyChip journey={profile.journey} /></DetailRow>
              <DetailRow label="Qualification"><QualificationChip state={profile.qualification} /></DetailRow>
              <DetailRow label="Relationship">
                {profile.marker === 'NONE' ? 'Active' : (
                  <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
                )}
              </DetailRow>
              {profile.marker_reason && (
                <DetailRow label="Reason">{profile.marker_reason}</DetailRow>
              )}
            </dl>
          </section>

          <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
            <h2 className="font-semibold text-ink">Business footprint</h2>
            <dl className="mt-2">
              <DetailRow label="Export markets">{profile.export_markets?.length ? profile.export_markets.join(', ') : '—'}</DetailRow>
              <DetailRow label="Products">{profile.products?.length ? profile.products.join(', ') : '—'}</DetailRow>
              <DetailRow label="Created">{formatDate(profile.created_at)}</DetailRow>
              <DetailRow label="Last updated">{formatDate(profile.updated_at)}</DetailRow>
            </dl>
          </section>
        </div>
      </div>
    </div>
  );
}
