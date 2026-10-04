/**
 * One lamp of the grammar in `lamps.ts`, drawn as a small SVG so it is crisp at
 * any size and needs no font. Shape carries the state; the colour repeats it.
 *
 * Two overlays (§6.1): a dashed ink ring for **awaiting approval** (nothing has
 * happened yet, so it is not a colour) and an attention dot for **Re-KYC due**.
 *
 * Decorative by default — the words next to it say the state. Pass `label` where
 * the lamp stands alone (the card-size Standing) and it becomes an image with that
 * name.
 */

import { cn } from '@/lib/cn';

import { MEANING_SOLID, type LampShape, type Meaning } from './lamps';

const R = 6;

function Shape({ shape }: { shape: LampShape }) {
  switch (shape) {
    case 'empty':
      return <circle cx="8" cy="8" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.2 2.2" />;
    case 'full':
      return <circle cx="8" cy="8" r={R + 0.75} fill="currentColor" />;
    case 'quarter':
    case 'half':
    case 'three': {
      const end = { quarter: [14, 8], half: [8, 14], three: [2, 8] }[shape];
      const large = shape === 'three' ? 1 : 0;
      return (
        <>
          <circle cx="8" cy="8" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d={`M8 8 L8 2 A${R} ${R} 0 ${large} 1 ${end[0]} ${end[1]} Z`} fill="currentColor" />
        </>
      );
    }
    case 'check':
      return (
        <>
          <circle cx="8" cy="8" r={R + 0.75} fill="currentColor" />
          <path d="M5 8.2 L7.1 10.2 L11 6" fill="none" stroke="rgb(var(--surface))" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
        </>
      );
    case 'cross':
      return (
        <>
          <circle cx="8" cy="8" r={R + 0.75} fill="currentColor" />
          <path d="M5.6 5.6 L10.4 10.4 M10.4 5.6 L5.6 10.4" stroke="rgb(var(--surface))" strokeWidth="1.6" strokeLinecap="round" />
        </>
      );
    case 'pause':
      return (
        <>
          <rect x="4.5" y="3" width="2.5" height="10" rx="1" fill="currentColor" />
          <rect x="9" y="3" width="2.5" height="10" rx="1" fill="currentColor" />
        </>
      );
    case 'question':
      return (
        <>
          <circle cx="8" cy="8" r={R} fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M6.3 6.4 A1.8 1.8 0 1 1 8.6 8.1 C8.1 8.3 8 8.6 8 9.2" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
          <circle cx="8" cy="11.2" r="0.9" fill="currentColor" />
        </>
      );
    case 'triangle':
      return <path d="M8 2.2 L14.2 13.2 L1.8 13.2 Z" fill="currentColor" strokeLinejoin="round" />;
    case 'square':
      return <rect x="2.5" y="2.5" width="11" height="11" rx="1.5" fill="currentColor" />;
    case 'dash':
      return <rect x="2.5" y="7" width="11" height="2" rx="1" fill="currentColor" />;
  }
}

export function Lamp({
  shape,
  meaning,
  size = 14,
  label,
  awaitingApproval = false,
  attentionDot = false,
  className,
}: {
  shape: LampShape;
  meaning: Meaning;
  size?: number;
  /** Set only where nothing beside the lamp names the state. */
  label?: string;
  awaitingApproval?: boolean;
  attentionDot?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn('relative inline-flex shrink-0', MEANING_SOLID[meaning], className)}
      style={{ width: size, height: size }}
      {...(label ? { role: 'img', 'aria-label': label } : { 'aria-hidden': true })}
      data-lamp={shape}
      data-meaning={meaning}
    >
      <svg viewBox="0 0 16 16" width={size} height={size} focusable="false">
        <Shape shape={shape} />
      </svg>
      {awaitingApproval && (
        <span
          className="absolute -inset-[3px] rounded-full border border-dashed border-ink"
          data-overlay="awaiting-approval"
        />
      )}
      {attentionDot && (
        <span
          className="absolute -right-0.5 -top-0.5 h-[5px] w-[5px] rounded-full bg-attention-solid ring-2 ring-surface"
          data-overlay="rekyc-due"
        />
      )}
    </span>
  );
}
