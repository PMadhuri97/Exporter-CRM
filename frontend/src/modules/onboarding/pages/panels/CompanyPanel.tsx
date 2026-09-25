/**
 * The company record — **owner: Developer 2** (architecture §8.1, §9.2).
 *
 * The company's own attributes: identifiers, industry, footprint, and the
 * legacy onboarding requests attached to it. The gauges are other people's
 * panels.
 *
 * Two exports, both Developer 2's, because the page renders them in two
 * places: the profile grid sits above the conversation panel and the
 * onboarding-history table sits below it. Keeping them in one file keeps the
 * ownership boundary honest; splitting them across two files would have meant
 * either a second Dev 2 file or moving the history section, and moving it
 * would have changed what the page looks like.
 *
 * Mechanical move out of `ExporterDetailPage.tsx` — markup and classes are
 * byte-identical to what the page rendered before.
 */

import { ExternalLink } from 'lucide-react';

import { DetailRow, EmptySection } from '@/components';
import { formatDate, humanize } from '@/lib/format';
import { MaskedValue } from '@/platform/mask';

import type { ExporterProfileDetail } from '../../types';

export function CompanyPanel({ profile }: { profile: ExporterProfileDetail }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
      <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
        <h2 className="font-semibold text-ink">Exporter profile</h2>
        <dl className="mt-2">
          <DetailRow label="PAN"><MaskedValue value={profile.pan} /></DetailRow>
          <DetailRow label="GSTIN"><MaskedValue value={profile.gstin} /></DetailRow>
          <DetailRow label="IEC"><MaskedValue value={profile.iec} /></DetailRow>
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
  );
}

/**
 * Requests on the legacy onboarding path linked to this company.
 *
 * Read-only, and on its way out: section 2.4 puts the legacy onboarding path
 * formally out of scope, and task L2-03 moves the company's name off
 * `OnboardingRequest` onto the company record. Until that lands, this table is
 * where the name visibly comes from.
 */
export function OnboardingHistorySection({
  profile,
}: {
  profile: ExporterProfileDetail;
}) {
  return (
    <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between gap-3">
        <div>
          <h2 className="font-semibold text-ink">Onboarding history</h2>
          <p className="mt-0.5 text-sm text-ink-muted">Requests linked to this exporter record.</p>
        </div>
        <span className="text-xs tabular-nums text-ink-faint">{profile.onboarding_history.length} total</span>
      </div>
      {profile.onboarding_history.length === 0 ? <EmptySection>No onboarding requests yet.</EmptySection> : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full text-left text-sm">
            <thead><tr className="border-b border-border text-xs uppercase tracking-wide text-ink-faint"><th className="px-4 py-2.5 font-medium">Company</th><th className="px-4 py-2.5 font-medium">Status</th><th className="px-4 py-2.5 font-medium">Initiated</th><th className="px-4 py-2.5 font-medium">Completed</th><th className="px-4 py-2.5 font-medium">Rejection</th></tr></thead>
            <tbody className="divide-y divide-border">{profile.onboarding_history.map((entry) => <tr key={entry.onboarding_id}><td className="px-4 py-3 font-medium text-ink">{entry.legal_name}</td><td className="px-4 py-3 text-ink-muted">{humanize(entry.status)}</td><td className="px-4 py-3 text-ink-muted">{formatDate(entry.initiated_at)}</td><td className="px-4 py-3 text-ink-muted">{formatDate(entry.completed_at)}</td><td className="px-4 py-3 text-ink-muted">{entry.rejection_category ? humanize(entry.rejection_category) : '—'}</td></tr>)}</tbody>
          </table>
        </div>
      )}
    </section>
  );
}
