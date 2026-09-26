/**
 * The company list — **owner: Developer 2** (L2-14).
 *
 * Every filter runs on the server: the journey tabs, qualification, marker and
 * the name search. That includes the rule that ENDED companies leave the
 * default list and come back for a search or the "Ended" marker filter —
 * this page does not re-implement it, it just asks.
 */

import { useState } from 'react';
import { Link } from 'react-router-dom';

import { MaskedValue } from '@/platform/mask';

import { JourneyChip, MarkerBadge, QualificationChip } from '../components';
import {
  JOURNEY_LABEL,
  JOURNEY_STAGES,
  MARKER_LABEL,
  QUALIFICATION_LABEL,
} from '../constants';
import { useExporterProfiles } from '../hooks';
import type { ExporterJourney, ExporterMarker, QualificationState } from '../types';

type Tab = 'ALL' | ExporterJourney;
const TABS: Tab[] = ['ALL', ...JOURNEY_STAGES];
const QUALIFICATION_OPTIONS = Object.keys(QUALIFICATION_LABEL) as QualificationState[];
const MARKER_OPTIONS = Object.keys(MARKER_LABEL) as ExporterMarker[];
const COLUMNS = 6;

function TableSkeletonRow() {
  return (
    <tr>
      {Array.from({ length: COLUMNS }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <div className="h-4 w-24 animate-pulse rounded bg-surface-sunken" />
        </td>
      ))}
    </tr>
  );
}

export function ExportersListPage() {
  const [searchInput, setSearchInput] = useState('');
  const [nameFilter, setNameFilter] = useState('');
  const [tab, setTab] = useState<Tab>('ALL');
  const [qualification, setQualification] = useState<QualificationState | ''>('');
  const [marker, setMarker] = useState<ExporterMarker | ''>('');

  const { data, isLoading, isError } = useExporterProfiles({
    name: nameFilter || undefined,
    journey: tab === 'ALL' ? undefined : tab,
    qualification: qualification || undefined,
    marker: marker || undefined,
  });
  const profiles = data?.profiles ?? [];
  const filtering = Boolean(nameFilter || qualification || marker || tab !== 'ALL');

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink">Exporters</h1>
          <p className="text-sm text-ink-muted">
            Find and manage exporter relationships. Ended relationships are hidden
            unless you search for them or filter by “Ended”.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            to="/exporters/import"
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            Import CSV
          </Link>
          <Link
            to="/exporters/rxil-intake"
            className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-ink hover:bg-surface-subtle"
          >
            RXIL intake
          </Link>
          <Link
            to="/exporters/new"
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
          >
            + Add Exporter
          </Link>
        </div>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setNameFilter(searchInput.trim());
          }}
        >
          <input
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Search by company name…"
            aria-label="Search by company name"
            className="w-72 rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
          />
        </form>
        <select
          aria-label="Qualification"
          className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
          value={qualification}
          onChange={(e) => setQualification(e.target.value as QualificationState | '')}
        >
          <option value="">Any qualification</option>
          {QUALIFICATION_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {QUALIFICATION_LABEL[value]}
            </option>
          ))}
        </select>
        <select
          aria-label="Relationship"
          className="rounded-lg border border-border px-3 py-2 text-sm text-ink"
          value={marker}
          onChange={(e) => setMarker(e.target.value as ExporterMarker | '')}
        >
          <option value="">Any relationship (ended hidden)</option>
          {MARKER_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {MARKER_LABEL[value]}
            </option>
          ))}
        </select>
      </div>

      <div className="mb-4 flex gap-1 border-b border-border" role="tablist">
        {TABS.map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            onClick={() => setTab(value)}
            className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              tab === value
                ? 'border-brand-500 text-brand-600'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            {value === 'ALL' ? 'All' : JOURNEY_LABEL[value]}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto rounded-lg border border-border bg-surface shadow-card">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-xs uppercase tracking-wide text-ink-faint">
              <th className="px-4 py-2.5 font-medium">Company Name</th>
              <th className="px-4 py-2.5 font-medium">PAN</th>
              <th className="px-4 py-2.5 font-medium">GSTIN</th>
              <th className="px-4 py-2.5 font-medium">Journey</th>
              <th className="px-4 py-2.5 font-medium">Qualification</th>
              <th className="px-4 py-2.5 font-medium">Owner</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => <TableSkeletonRow key={i} />)}

            {isError && (
              <tr>
                <td colSpan={COLUMNS} className="px-4 py-8 text-center text-sm text-status-failed">
                  Couldn't load exporters. Try again shortly.
                </td>
              </tr>
            )}

            {!isLoading && !isError && profiles.length === 0 && (
              <tr>
                <td colSpan={COLUMNS} className="px-4 py-8 text-center text-sm text-ink-muted">
                  {filtering ? (
                    'No exporters match this filter.'
                  ) : (
                    <>
                      No exporters yet —{' '}
                      <Link to="/exporters/new" className="font-medium text-brand-600 underline">
                        Add Exporter
                      </Link>
                    </>
                  )}
                </td>
              </tr>
            )}

            {!isLoading &&
              !isError &&
              profiles.map((profile) => (
                <tr key={profile.customer_id} className="hover:bg-surface-subtle">
                  <td className="px-4 py-3 font-medium text-ink">
                    <Link
                      to={`/exporters/${profile.customer_id}`}
                      className="hover:text-brand-600 hover:underline"
                    >
                      {profile.name ?? <span className="italic text-ink-faint">Unnamed lead</span>}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <MaskedValue value={profile.pan} />
                  </td>
                  <td className="px-4 py-3">
                    <MaskedValue value={profile.gstins[0] ?? null} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1.5">
                      <JourneyChip journey={profile.journey} />
                      <MarkerBadge marker={profile.marker} reason={profile.marker_reason} />
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <QualificationChip state={profile.qualification} />
                  </td>
                  <td className="px-4 py-3 text-ink-muted">{profile.relationship_manager ?? '—'}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
