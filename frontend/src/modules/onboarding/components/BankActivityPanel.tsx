/**
 * Bank-linked activity, stated honestly — **owner: Developer 4B** (verification-and-screening.md §8;
 * architecture §7.6's "honest bank panel"; 4B-7).
 *
 * No bank-monitoring provider feed is connected. The server says so
 * (`provider_feed_connected: false`, `provider_feed_status: NOT_CONNECTED`, and a
 * message), and this panel repeats it. It never shows "0 connected accounts" or
 * "0 open flags" as if accounts had been checked and found clean: with no feed, there
 * is nothing to count. No finding is ever invented; stored findings, if any exist,
 * are listed as stored.
 */

import { Landmark, PlugZap } from 'lucide-react';

import { formatDateTime, humanize } from '@/lib/format';

import { useBankActivity } from '../hooks';

import { VerificationStatusChip } from './VerificationStatusChip';

export function BankActivityPanel({ customerId }: { customerId: string }) {
  const query = useBankActivity(customerId);
  const data = query.data;

  if (query.isLoading) {
    return <div className="h-24 animate-pulse rounded bg-surface-sunken" />;
  }
  if (query.isError || !data) {
    return (
      <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
        Could not load bank activity.{' '}
        <button type="button" className="underline" onClick={() => void query.refetch()}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-border bg-surface-subtle p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-surface p-2 text-brand-600 shadow-sm">
            <Landmark size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-ink">Bank-linked activity</h3>
              {data.provider_feed_connected ? (
                <span className="rounded-full bg-emerald-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                  Feed connected
                </span>
              ) : (
                <span
                  data-testid="bank-feed-status"
                  className="inline-flex items-center gap-1 rounded-full border border-dashed border-border-strong bg-surface px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-ink-muted"
                >
                  <PlugZap size={11} /> Not connected
                </span>
              )}
            </div>
            <p className="mt-1 text-sm leading-6 text-ink-muted">{data.provider_feed_message}</p>
          </div>
        </div>
      </div>

      {data.provider_feed_connected && (
        // Counts mean something only when a feed is connected and has reported.
        <div className="grid gap-3 md:grid-cols-3">
          {[
            ['Connected accounts', String(data.connected_accounts)],
            ['Last bank sync', formatDateTime(data.last_synced_at)],
            ['Open suspicious activity flags', String(data.open_findings)],
          ].map(([label, value]) => (
            <div key={label} className="rounded-lg border border-border p-4">
              <p className="text-xs text-ink-faint">{label}</p>
              <p className="mt-1 text-lg font-semibold text-ink">{value}</p>
            </div>
          ))}
        </div>
      )}

      {data.findings.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border-strong px-4 py-6 text-center">
          <p className="text-sm font-medium text-ink">
            {data.provider_feed_connected
              ? 'No bank activity findings'
              : 'Bank activity is not being monitored'}
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            {data.provider_feed_connected
              ? 'The provider feed has reported no suspicious activity for this exporter.'
              : 'With no provider feed, there is nothing to report — this is not a clean result.'}
          </p>
        </div>
      ) : (
        <div className="rounded-lg border border-border px-4">
          {data.findings.map((finding) => (
            <div key={finding.id} className="border-b border-border py-4 last:border-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-ink">{finding.title}</span>
                <VerificationStatusChip value={finding.risk_level} />
                <VerificationStatusChip value={finding.status} />
              </div>
              <p className="mt-1 text-xs text-ink-faint">
                {finding.provider} · {humanize(finding.finding_type)} ·{' '}
                {formatDateTime(finding.detected_at)}
              </p>
              {finding.description && (
                <p className="mt-2 text-sm text-ink-muted">{finding.description}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
