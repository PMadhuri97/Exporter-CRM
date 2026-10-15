/**
 * Bank-linked activity, stated honestly (verification-and-screening.md §8;
 * architecture §7.6's "honest bank panel").
 *
 * No bank-monitoring provider feed is connected, and none is planned, so there is no
 * server route to ask: the panel says so itself. It never shows "0 connected accounts"
 * or "0 open flags" as if accounts had been checked and found clean — with no feed,
 * there is nothing to count.
 */

import { Icon } from '@/design/icons';

export function BankActivityPanel() {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-line bg-paper p-4">
        <div className="flex items-start gap-3">
          <div className="rounded-lg bg-surface p-2 text-ink shadow-sm">
            <Icon.branch size={18} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-body font-semibold text-ink">Bank-linked activity</h3>
              <span
                data-testid="bank-feed-status"
                className="inline-flex items-center gap-1 rounded-sm border border-dashed border-line-strong bg-surface px-2 py-1 text-caption font-medium text-ink-2"
              >
                <Icon.notConnected size={11} /> Not connected
              </span>
            </div>
            <p className="mt-1 text-body leading-6 text-ink-2">
              No bank-monitoring feed is connected. Bank activity is not being monitored for
              this company.
            </p>
          </div>
        </div>
      </div>
      <div className="rounded-lg border border-dashed border-line-strong px-4 py-6 text-center">
        <p className="text-body font-medium text-ink">Bank activity is not being monitored</p>
        <p className="mt-1 text-caption text-ink-2">
          With no feed, there is nothing to report — this is not a clean result.
        </p>
      </div>
    </div>
  );
}
