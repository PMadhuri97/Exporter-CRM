import { cn } from '@/lib/cn';

/**
 * The brand mark (frontend-plan §5.7): a solid ink square with a lower-case
 * italic serif *a* knocked out in paper, beside "Aner Labs" in the sans at 600.
 * No hue and no gradient. A placeholder until the business supplies a logo;
 * the favicon (`public/favicon.svg`) is the square alone.
 */
export function BrandMark({
  wordmark = true,
  size = 'md',
  className,
}: {
  /** Off where only the square fits (the collapsed rail). */
  wordmark?: boolean;
  size?: 'sm' | 'md';
  className?: string;
}) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <span
        aria-hidden
        className={cn(
          'flex shrink-0 items-center justify-center rounded-[5px] bg-ink font-display italic leading-none text-paper',
          size === 'md' ? 'h-8 w-8 pb-1 text-[22px]' : 'h-6 w-6 pb-0.5 text-[17px]',
        )}
      >
        a
      </span>
      {wordmark ? (
        <span className="whitespace-nowrap text-body font-semibold text-ink">Aner Labs</span>
      ) : (
        <span className="sr-only">Aner Labs</span>
      )}
    </span>
  );
}
