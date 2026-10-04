/**
 * A label/value row inside a `<dl>`.
 *
 * Promoted out of `ExporterDetailPage.tsx` when that page was split into
 * per-owner panels: more than one panel shows label/value pairs, and a
 * component copied into each would let them drift apart in alignment and
 * spacing one edit at a time.
 *
 * Moved verbatim; no markup or class changed then. Since: a long unbroken value (a
 * buyer's contact email) wraps inside its cell instead of running into the field
 * beside it — `min-w-0` lets the row shrink within a multi-column `<dl>`, and
 * `overflow-wrap: anywhere` gives the value somewhere to break.
 */

export function DetailRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid min-w-0 grid-cols-[9rem_1fr] gap-4 border-b border-line py-3 last:border-b-0">
      <dt className="text-secondary text-ink-3">{label}</dt>
      <dd className="min-w-0 text-body text-ink [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}
