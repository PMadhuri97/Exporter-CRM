/**
 * A label/value row inside a `<dl>`.
 *
 * Promoted out of `ExporterDetailPage.tsx` when that page was split into
 * per-owner panels: more than one panel shows label/value pairs, and a
 * component copied into each would let them drift apart in alignment and
 * spacing one edit at a time.
 *
 * Moved verbatim; no markup or class changed.
 */

export function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-[9rem_1fr] gap-4 border-b border-border py-3 last:border-b-0">
      <dt className="text-sm text-ink-faint">{label}</dt>
      <dd className="min-w-0 text-sm text-ink">{children}</dd>
    </div>
  );
}
