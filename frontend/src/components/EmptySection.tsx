/**
 * The "there is nothing here yet" state for a panel.
 *
 * A dashed border rather than a bare line of text, so an empty section reads
 * as a deliberate state rather than a section that failed to load.
 *
 * Promoted verbatim out of `ExporterDetailPage.tsx` during the panel split.
 */

export function EmptySection({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-4 py-6 text-center text-sm text-ink-muted">
      {children}
    </div>
  );
}
