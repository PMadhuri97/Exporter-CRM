import { FileText, Info } from 'lucide-react';
import { useMemo, useState } from 'react';

import { useDocumentRequirements } from '../hooks';
import type { DocumentRequirementsParams } from '../types';

/**
 * What this exporter will be asked to provide — read-only, and deliberately so.
 *
 * No document storage exists in this build: there is no upload endpoint, no
 * object store, and no per-document status to show. What exists is the policy
 * (`GET /onboarding/document-requirements`), so this panel shows the policy and
 * says plainly that collection comes later. That is the honest alternative to
 * an empty "Documents" panel that reads as a bug, and to an upload control that
 * would 404.
 *
 * Why the profile is picked here rather than read off the exporter
 * ----------------------------------------------------------------
 * The policy matches on entity type, registration country, sector code and
 * corridor, and none of those four are on `exporter_profile` — they live on
 * `onboarding_request`, which this page does not load (its `onboarding_history`
 * carries only id, status, legal name and dates). Rather than guess, the panel
 * asks: the two required fields default to the shape almost every record in
 * this product has (an Indian corporation, per the RXIL flow), and an operator
 * can change them to see what a different profile would owe. Every control here
 * only changes *which policy question is asked*; nothing it does writes.
 *
 * Replace the defaults with the exporter's own values once the detail response
 * carries them.
 */

const ENTITY_TYPES = ['CORPORATION', 'PARTNERSHIP', 'SOLE_TRADER', 'TRUST', 'FUND'];

/** Matches the GitOps policy's own `profiles[].registration_country` values,
 *  plus the corridor those profiles are written for. */
const COUNTRIES = ['IN', 'US', 'GB', 'SG', 'AE'];

function humanizeDocumentType(value: string): string {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

function validityLabel(maxAgeDays: number | null): string {
  if (maxAgeDays === null) return 'Any age';
  if (maxAgeDays % 365 === 0) {
    const years = maxAgeDays / 365;
    return years === 1 ? 'Within 12 months' : `Within ${years} years`;
  }
  if (maxAgeDays % 30 === 0) return `Within ${maxAgeDays / 30} months`;
  return `Within ${maxAgeDays} days`;
}

export function DocumentRequirementsSection({ industry }: { industry?: string | null }) {
  const [entityType, setEntityType] = useState('CORPORATION');
  const [registrationCountry, setRegistrationCountry] = useState('IN');
  // The CRM records a free-text `industry` ("Textiles"), not the FATF sector
  // code the policy matches on ("DNFBP"). Offering it as the initial value is
  // useful; treating the two as the same field would not be, so it is an
  // editable input rather than a silent mapping.
  const [sectorCode, setSectorCode] = useState(industry?.trim() ?? '');

  const params = useMemo<DocumentRequirementsParams>(
    () => ({
      entityType,
      registrationCountry,
      sectorCode: sectorCode.trim() || undefined,
    }),
    [entityType, registrationCountry, sectorCode],
  );
  const query = useDocumentRequirements(params);
  const data = query.data;

  return (
    <section
      data-extension="document-requirements"
      className="rounded-lg border border-border bg-surface p-5 shadow-card"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <FileText size={18} className="text-brand-600" />
            <h2 className="font-semibold text-ink">Required documents</h2>
          </div>
          <p className="mt-1 text-sm text-ink-muted">
            What the compliance policy will ask this exporter for.
          </p>
        </div>
        {data && (
          <span className="rounded-full bg-surface-sunken px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
            Policy v{data.policy_version}
          </span>
        )}
      </div>

      <div className="mt-3 flex items-start gap-2 rounded-md bg-surface-subtle px-3 py-2 text-xs leading-5 text-ink-faint">
        <Info size={14} className="mt-0.5 shrink-0" />
        <span>
          Read-only. Document collection is a later phase — nothing can be uploaded or
          marked received yet, so this list is what <em>will</em> be required, not what
          has been provided.
        </span>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-3">
        <label className="text-xs font-medium text-ink-faint">
          Entity type
          <select
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-brand-500"
            value={entityType}
            onChange={(event) => setEntityType(event.target.value)}
          >
            {ENTITY_TYPES.map((value) => (
              <option key={value} value={value}>
                {humanizeDocumentType(value.toLowerCase())}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-ink-faint">
          Registration country
          <select
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-brand-500"
            value={registrationCountry}
            onChange={(event) => setRegistrationCountry(event.target.value)}
          >
            {COUNTRIES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-medium text-ink-faint">
          Sector code
          <input
            className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-ink outline-none focus:border-brand-500"
            value={sectorCode}
            placeholder="e.g. DNFBP"
            onChange={(event) => setSectorCode(event.target.value)}
          />
        </label>
      </div>

      <div className="mt-4">
        {query.isLoading ? (
          <div className="h-24 animate-pulse rounded bg-surface-sunken" />
        ) : query.isError ? (
          <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            Could not load document requirements.{' '}
            <button type="button" className="font-medium underline" onClick={() => void query.refetch()}>
              Retry
            </button>
          </div>
        ) : (data?.required_documents.length ?? 0) === 0 ? (
          <div className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-8 text-center">
            <p className="text-sm font-medium text-ink">No documents required</p>
            <p className="mx-auto mt-1 max-w-md text-xs leading-5 text-ink-muted">
              The policy has no profile or conditional rule matching this combination. That
              is a configuration answer, not an empty state — a different entity type,
              country or sector may well require several.
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
                  <th className="px-4 py-2.5 font-medium">Document</th>
                  <th className="px-4 py-2.5 font-medium">Accepted age</th>
                  <th className="px-4 py-2.5 font-medium">Policy note</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data!.required_documents.map((document) => (
                  <tr key={document.document_type}>
                    <td className="px-4 py-3 font-medium text-ink">
                      {humanizeDocumentType(document.document_type)}
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {validityLabel(document.max_age_days)}
                    </td>
                    <td className="px-4 py-3 text-ink-faint">
                      {document.validity_description ?? '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
