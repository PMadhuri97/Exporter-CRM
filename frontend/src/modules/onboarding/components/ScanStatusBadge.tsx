/**
 * A document's scan status, and who decided it — **owner: Developer 3B** (L3-11b).
 *
 * Two things on purpose, not one.
 *
 * **The status**, in the semantic colours the design principles fix: green for a
 * clean result, red for quarantined, amber for a failed scan, neutral for pending.
 *
 * **The scanner's name**, whenever a verdict has actually been reached. In this
 * build that is always `pass-through` — a placeholder that checks nothing
 * (assumption A9) — so a badge reading only "Available" would quietly imply a
 * malware scan happened. Gate §7.6 blocks real exporter documents until a real
 * scanner is behind the interface, and until then the screen says which "scanner"
 * cleared the file.
 *
 * Provider-style values are stored lowercase and displayed uppercase, the same rule
 * verification providers follow (§7.5, decision D4).
 */

import { AlertTriangle, CheckCircle2, Clock, ShieldAlert } from 'lucide-react';

import type { DocumentScanStatus } from '../types';

const LOOK: Record<
  DocumentScanStatus,
  { label: string; className: string; icon: typeof Clock; title: string }
> = {
  PENDING_SCAN: {
    label: 'Pending scan',
    className: 'bg-surface-sunken text-ink-muted',
    icon: Clock,
    title: 'Waiting on the scan step. It cannot be opened yet.',
  },
  AVAILABLE: {
    label: 'Available',
    className: 'bg-status-passed/10 text-status-passed',
    icon: CheckCircle2,
    title: 'Passed the scan step and can be opened.',
  },
  QUARANTINED: {
    label: 'Quarantined',
    className: 'bg-status-failed/10 text-status-failed',
    icon: ShieldAlert,
    title: 'The scan step rejected this file. It is never served.',
  },
  SCAN_FAILED: {
    label: 'Scan failed',
    className: 'bg-status-review/10 text-status-review',
    icon: AlertTriangle,
    title: 'The scan step could not decide, so the file is not served.',
  },
};

export function ScanStatusBadge({
  status,
  scannerName,
}: {
  status: DocumentScanStatus;
  /** Which scanner reached the verdict. Shown whenever present — see the module
   * docstring for why hiding `pass-through` would be dishonest. */
  scannerName?: string | null;
}) {
  const look = LOOK[status];
  const Icon = look.icon;

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        title={look.title}
        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${look.className}`}
      >
        <Icon size={11} />
        {look.label}
      </span>
      {scannerName && (
        <span
          className="text-xs uppercase tracking-wide text-ink-faint"
          title={
            scannerName === 'pass-through'
              ? 'This build ships a labelled pass-through: no malware check was performed.'
              : `Scanned by ${scannerName}.`
          }
        >
          {scannerName}
        </span>
      )}
    </span>
  );
}
