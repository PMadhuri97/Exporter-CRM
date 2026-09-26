/**
 * The company record — **owner: Developer 2** (architecture §8.1, §9.2).
 *
 * The company's own attributes: identity, identifiers, industry and
 * footprint. The gauges are other people's panels.
 *
 * The onboarding-history table that used to sit below the conversation panel
 * is gone (L2-03). The company's name was taken from it; the name is now part
 * of the company's own identity, shown in the page header, and the legacy
 * onboarding path's records stay with that path.
 */

import { ExternalLink } from 'lucide-react';

import { DetailRow } from '@/components';
import { formatDate, humanize } from '@/lib/format';
import { MaskedValue } from '@/platform/mask';

import type { ExporterProfileDetail } from '../../types';

export function CompanyPanel({ profile }: { profile: ExporterProfileDetail }) {
  return (
    <div className="grid gap-5 xl:grid-cols-[1.35fr_1fr]">
      <section className="rounded-lg border border-border bg-surface p-5 shadow-card">
        <h2 className="font-semibold text-ink">Exporter profile</h2>
        <dl className="mt-2">
          <DetailRow label="Country">{profile.country ?? '—'}</DetailRow>
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

