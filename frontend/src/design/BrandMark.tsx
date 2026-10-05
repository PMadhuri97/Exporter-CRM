import { cn } from '@/lib/cn';

/**
 * The brand (frontend-plan §5.8): the "Aner Labs" wordmark at 16/600 with the
 * product, "Exporter CRM", in grey beside it — the way Salesforce and Dynamics name
 * the app in their header. A placeholder until a logo exists. The favicon
 * (`public/favicon.svg`) is a white "A" on the brand blue, the same as `mark`.
 */
export function BrandMark({
  wordmark = true,
  product = true,
  mark = false,
  className,
}: {
  /** Off where only the square fits (the collapsed side navigation). */
  wordmark?: boolean;
  /** "Exporter CRM" beside the wordmark. */
  product?: boolean;
  /** The square "A", as on the favicon. */
  mark?: boolean;
  className?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-2', className)}>
      {(mark || !wordmark) && (
        <span
          aria-hidden
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded bg-accent-solid text-[13px] font-bold leading-none text-white"
        >
          A
        </span>
      )}
      {wordmark ? (
        <span className="flex items-baseline gap-2 whitespace-nowrap">
          <span className="text-heading font-semibold text-ink">Aner Labs</span>
          {product && <span className="text-body text-ink-3">Exporter CRM</span>}
        </span>
      ) : (
        <span className="sr-only">Aner Labs Exporter CRM</span>
      )}
    </span>
  );
}
