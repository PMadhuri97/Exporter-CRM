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

import { AlertTriangle } from 'lucide-react';
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { Button, DetailRow, FormError, Input, Panel } from '@/components';
import { formatDate, humanize } from '@/lib/format';
import { useCurrentUser } from '@/platform/auth';
import { MaskedValue, canReveal } from '@/platform/mask';

import {
  DuplicatePanMessage,
  JourneyChip,
  MarkerBadge,
  QualificationChip,
  duplicatePanHolder,
} from '../../components';
import { useUpdateExporterProfile } from '../../hooks';
import { paths } from '../../paths';
import type { ExporterProfileDetail, UpdateExporterProfileRequest } from '../../types';

/** The editable fields, as the form holds them (lists as comma-separated text). */
interface ProfileDraft {
  name: string;
  country: string;
  pan: string;
  iec: string;
  cin: string;
  registration_number: string;
  relationship_manager: string;
  industry: string;
  export_markets: string;
  products: string;
  year_established: string;
}

const FIELDS: { key: keyof ProfileDraft; label: string }[] = [
  { key: 'name', label: 'Company name' },
  { key: 'country', label: 'Country' },
  { key: 'pan', label: 'PAN' },
  { key: 'iec', label: 'IEC' },
  { key: 'cin', label: 'CIN' },
  { key: 'registration_number', label: 'Registration number' },
  { key: 'relationship_manager', label: 'Owner' },
  { key: 'industry', label: 'Industry' },
  { key: 'export_markets', label: 'Export markets (comma-separated)' },
  { key: 'products', label: 'Products (comma-separated)' },
  { key: 'year_established', label: 'Year established' },
];

const LIST_FIELDS = new Set<keyof ProfileDraft>(['export_markets', 'products']);

/**
 * Identifiers masked for roles that may not reveal them. The server masks the
 * foreign registration number like CIN (task 3.8), so it is listed here too —
 * otherwise the form would show bullets as if they were the value and send them
 * back on save.
 */
const MASKED_FIELDS = new Set<keyof ProfileDraft>([
  'pan',
  'iec',
  'cin',
  'registration_number',
]);

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
    iec: revealIdentifiers ? (profile.iec ?? '') : '',
    cin: revealIdentifiers ? (profile.cin ?? '') : '',
    registration_number: revealIdentifiers ? (profile.registration_number ?? '') : '',
    relationship_manager: profile.relationship_manager ?? '',
    industry: profile.industry ?? '',
    export_markets: (profile.export_markets ?? []).join(', '),
    products: (profile.products ?? []).join(', '),
    year_established: profile.year_established?.toString() ?? '',
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
      // Anything but digits goes as typed, so the server refuses it (422).
      // `Number('abc')` is NaN, which JSON sends as null — clearing the year.
      changes[key] = text ? (/^\d+$/.test(text) ? Number(text) : text) : null;
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
  // The company already holding a PAN just typed, shown as a link in the form.
  const [panHolder, setPanHolder] = useState<string | null>(null);
  const changes = changesBetween(initial, draft);
  const changed = Object.keys(changes).length > 0;

  return (
    <form
      aria-label="Edit profile"
      className="mt-3 space-y-3"
      onSubmit={(e) => {
        e.preventDefault();
        setPanHolder(null);
        mutation.mutate(changes, {
          onSuccess: () => {
            toast.success('Profile updated');
            onDone();
          },
          onError: (error) => {
            const holder = duplicatePanHolder(error);
            if (holder) setPanHolder(holder);
            else toast.error(error.message);
          },
        });
      }}
    >
      <FormError>{panHolder && <DuplicatePanMessage holderId={panHolder} />}</FormError>
      <div className="grid gap-3 md:grid-cols-2">
        {FIELDS.map(({ key, label }) => (
          <label key={key} className="flex flex-col gap-1 text-sm text-ink-muted">
            {label}
            <Input
              placeholder={!reveal && MASKED_FIELDS.has(key) ? 'Hidden — type to replace' : undefined}
              inputMode={key === 'year_established' ? 'numeric' : undefined}
              value={draft[key]}
              onChange={(e) => setDraft((current) => ({ ...current, [key]: e.target.value }))}
            />
          </label>
        ))}
      </div>
      <div className="flex justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onDone}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" disabled={!changed} loading={mutation.isPending}>
          Save profile
        </Button>
      </div>
    </form>
  );
}

/**
 * "another company", or "2 other companies: company 1 and company 2" — one link per
 * company, by id only, as the warning gives them.
 */
function OtherCompanies({ ids }: { ids: string[] }) {
  const link = (id: string, text: string) => (
    <Link to={paths.company(id)} className="text-brand-600 underline">
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
          className="rounded-lg border border-status-review/40 bg-status-review/10 p-4 text-sm text-ink"
        >
          <div className="flex items-center gap-2 font-medium">
            <AlertTriangle size={15} className="text-status-review" />
            A GSTIN on this company is also on another company
          </div>
          <ul className="mt-2 space-y-1">
            {profile.gstin_warnings.map((warning) => (
              <li key={warning.gstin}>
                <MaskedValue value={warning.gstin} /> — also on{' '}
                <OtherCompanies ids={warning.other_customer_ids} />
              </li>
            ))}
          </ul>
        </section>
      )}

      <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
        <Panel
          title="Company profile"
          actions={
            canEdit &&
            !editing && (
              <Button size="sm" onClick={() => setEditing(true)}>
                Edit profile
              </Button>
            )
          }
        >
          {editing ? (
            <ProfileEditForm profile={profile} onDone={() => setEditing(false)} />
          ) : (
            <dl>
              <DetailRow label="Country">{profile.country ?? '—'}</DetailRow>
              <DetailRow label="PAN"><MaskedValue value={profile.pan} /></DetailRow>
              {/* The GSTINs themselves are `GstRegistrationsSection` below (task
                  3.13): each is a branch with a state, a status, an address and
                  possibly a flag, and a list of bare values here would be a second,
                  poorer view of the same thing. The count stays, because "how many
                  states is this company registered in" belongs in the summary. */}
              <DetailRow label="GST registrations">
                {profile.gstins.length === 0
                  ? 'None'
                  : profile.gstins.length === 1
                    ? '1 active'
                    : `${profile.gstins.length} active`}
              </DetailRow>
              <DetailRow label="IEC"><MaskedValue value={profile.iec} /></DetailRow>
              <DetailRow label="CIN"><MaskedValue value={profile.cin} /></DetailRow>
              <DetailRow label="Registration number">
                <MaskedValue value={profile.registration_number} />
              </DetailRow>
              <DetailRow label="Source">{humanize(profile.source)}</DetailRow>
              <DetailRow label="Industry">{profile.industry ?? '—'}</DetailRow>
              <DetailRow label="Established">{profile.year_established ?? '—'}</DetailRow>
            </dl>
          )}
        </Panel>

        <div className="space-y-5">
          <Panel title="Where it stands">
            <dl>
              {/* A buyer-only company has no journey and no qualification: the
                  columns hold LEAD and NOT_YET_REVIEWED because they are NOT NULL
                  and `ck_exporter_profile_not_in_pipeline_start` requires it, not
                  because anyone judged them (plan P4-2, task 3.9). Chips here would
                  read as a sales stage that does not exist. */}
              {profile.pipeline_status === 'NOT_IN_PIPELINE' ? (
                <DetailRow label="Pipeline">
                  <span className="text-ink-muted">Not in pipeline — exists as a buyer</span>
                </DetailRow>
              ) : (
                <>
                  <DetailRow label="Journey"><JourneyChip journey={profile.journey} /></DetailRow>
                  <DetailRow label="Qualification"><QualificationChip state={profile.qualification} /></DetailRow>
                </>
              )}
              <DetailRow label="Relationship">
                {profile.marker === 'NONE' ? 'Active' : (
                  <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
                )}
              </DetailRow>
              {profile.marker_reason && (
                <DetailRow label="Reason">{profile.marker_reason}</DetailRow>
              )}
            </dl>
          </Panel>

          <Panel title="Business footprint">
            <dl>
              <DetailRow label="Export markets">{profile.export_markets?.length ? profile.export_markets.join(', ') : '—'}</DetailRow>
              <DetailRow label="Products">{profile.products?.length ? profile.products.join(', ') : '—'}</DetailRow>
              <DetailRow label="Created">{formatDate(profile.created_at)}</DetailRow>
              <DetailRow label="Last updated">{formatDate(profile.updated_at)}</DetailRow>
            </dl>
          </Panel>
        </div>
      </div>
    </div>
  );
}
