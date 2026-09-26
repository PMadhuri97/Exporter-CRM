import { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import { MaskedValue } from '@/platform/mask';

import { StageChip } from '../components';
import {
  STAGE_GROUPS,
  STAGE_GROUP_LABEL,
  STATUS_TO_STAGE_GROUP,
  type StageGroup,
} from '../constants';
import { useExporterProfiles } from '../hooks';

type TabValue = 'ALL' | StageGroup;
const TABS: TabValue[] = ['ALL', ...STAGE_GROUPS];

function TableSkeletonRow() {
  return (
    <tr>
      {Array.from({ length: 5 }).map((_, i) => (
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
  const [activeTab, setActiveTab] = useState<TabValue>('ALL');

  const { data, isLoading, isError } = useExporterProfiles({
    name: nameFilter || undefined,
  });

  const profiles = useMemo(() => data?.profiles ?? [], [data]);
  const visibleProfiles = useMemo(() => {
    if (activeTab === 'ALL') return profiles;
    return profiles.filter(
      (p) => STATUS_TO_STAGE_GROUP[p.lifecycle_status] === activeTab,
    );
  }, [profiles, activeTab]);

  const tabCounts = useMemo(() => {
    const counts: Partial<Record<TabValue, number>> = { ALL: profiles.length };
    for (const profile of profiles) {
      const group = STATUS_TO_STAGE_GROUP[profile.lifecycle_status];
      counts[group] = (counts[group] ?? 0) + 1;
    }
    return counts;
  }, [profiles]);

  return (
    <div>
      <div className="mb-5 flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-ink">Exporters</h1>
          <p className="text-sm text-ink-muted">
            Find and manage exporter relationships.
          </p>
        </div>
        <Link
          to="/exporters/new"
          className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          + Add Exporter
        </Link>
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          setNameFilter(searchInput.trim());
        }}
        className="mb-4"
      >
        <input
          type="search"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          placeholder="Search by company name…"
          className="w-full max-w-sm rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500 sm:w-80"
        />
      </form>

      <div className="mb-4 flex gap-1 border-b border-border">
        {TABS.map((tab) => (
          <button
            key={tab}
            type="button"
            onClick={() => setActiveTab(tab)}
            className={`border-b-2 px-3 py-2 text-sm font-medium transition-colors ${
              activeTab === tab
                ? 'border-brand-500 text-brand-600'
                : 'border-transparent text-ink-muted hover:text-ink'
            }`}
          >
            {tab === 'ALL' ? 'All' : STAGE_GROUP_LABEL[tab]}
            {tabCounts[tab] !== undefined && (
              <span className="ml-1.5 text-xs text-ink-faint">
                ({tabCounts[tab]})
              </span>
            )}
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
              <th className="px-4 py-2.5 font-medium">Stage</th>
              <th className="px-4 py-2.5 font-medium">Owner</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {isLoading &&
              Array.from({ length: 5 }).map((_, i) => (
                <TableSkeletonRow key={i} />
              ))}

            {isError && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-sm text-status-failed"
                >
                  Couldn't load exporters. Try again shortly.
                </td>
              </tr>
            )}

            {!isLoading && !isError && visibleProfiles.length === 0 && (
              <tr>
                <td
                  colSpan={5}
                  className="px-4 py-8 text-center text-sm text-ink-muted"
                >
                  {profiles.length === 0 ? (
                    <>
                      No exporters yet —{' '}
                      <Link
                        to="/exporters/new"
                        className="font-medium text-brand-600 underline"
                      >
                        Add Exporter
                      </Link>
                    </>
                  ) : (
                    'No exporters match this filter.'
                  )}
                </td>
              </tr>
            )}

            {!isLoading &&
              !isError &&
              visibleProfiles.map((profile) => {
                return (
                  <tr
                    key={profile.customer_id}
                    className="hover:bg-surface-subtle"
                  >
                    <td className="px-4 py-3 font-medium text-ink">
                      <Link
                        to={`/exporters/${profile.customer_id}`}
                        className="hover:text-brand-600 hover:underline"
                      >
                        {profile.name ?? (
                          <span className="italic text-ink-faint">
                            Unnamed lead
                          </span>
                        )}
                      </Link>
                    </td>
                    <td className="px-4 py-3">
                      <MaskedValue value={profile.pan} />
                    </td>
                    <td className="px-4 py-3">
                      <MaskedValue value={profile.gstin} />
                    </td>
                    <td className="px-4 py-3">
                      <StageChip status={profile.lifecycle_status} />
                    </td>
                    <td className="px-4 py-3 text-ink-muted">
                      {profile.relationship_manager ?? '—'}
                    </td>
                  </tr>
                );
              })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
