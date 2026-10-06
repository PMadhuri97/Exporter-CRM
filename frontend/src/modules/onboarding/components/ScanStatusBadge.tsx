/**
 * A document's scan status, and who decided it.
 *
 * Two things on purpose, not one.
 *
 * **The status**, in the semantic colours the design principles fix: green for a
 * clean result, red for quarantined, amber for a failed scan, neutral for pending.
 *
 * **The scanner's name**, when the caller passes one. In this build that is always
 * `pass-through` — a placeholder that checks nothing — so a badge reading only
 * "Available" must not be left to imply that a malware scan happened. Gate §7.6 blocks
 * real exporter documents until a real scanner is behind the interface, and until then
 * the screen has to say which "scanner" cleared the file.
 *
 * That disclosure is no longer made per row. `DocumentsByCategory` prints
 * "Prototype: pass-through scanner" once above its list, which says the same thing for
 * every file under it instead of repeating a word on each line. A caller that shows
 * documents **without** such a notice should pass `scannerName`, or the claim goes
 * unqualified.
 *
 * Provider-style values are stored lowercase and displayed uppercase, the same rule
 * verification providers follow.
 */


import { Tag } from '@/components';
import { Icon, type IconComponent } from '@/design/icons';

import type { DocumentScanStatus } from '../types';

const LOOK: Record<
  DocumentScanStatus,
  { label: string; className: string; icon: IconComponent; title: string }
> = {
  PENDING_SCAN: {
    label: 'Pending scan',
    className: 'bg-sunken text-ink-2',
    icon: Icon.clock,
    title: 'Waiting on the scan step. It cannot be opened yet.',
  },
  AVAILABLE: {
    label: 'Available',
    className: 'bg-positive-tint text-positive',
    icon: Icon.passed,
    title: 'Passed the scan step and can be opened.',
  },
  QUARANTINED: {
    label: 'Quarantined',
    className: 'bg-negative-tint text-negative',
    icon: Icon.flagged,
    title: 'The scan step rejected this file. It is never served.',
  },
  SCAN_FAILED: {
    label: 'Scan failed',
    className: 'bg-attention-tint text-attention',
    icon: Icon.warning,
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
  const Glyph = look.icon;

  return (
    <span className="inline-flex items-center gap-1.5">
      <Tag title={look.title} className={look.className} icon={<Glyph size={11} />}>
        {look.label}
      </Tag>
      {scannerName && (
        <span
          className="text-caption uppercase tracking-wide text-ink-3"
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
