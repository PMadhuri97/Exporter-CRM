/**
 * A status, risk or verdict pill for the verification workspace — **owner:
 * Developer 4B**. Shows the server's value, humanized; the colour is from
 * `chipClasses`.
 */

import { humanize } from '@/lib/format';

import { chipClasses } from './verification-labels';

export function VerificationStatusChip({ value }: { value: string }) {
  return (
    <span className={`inline-flex rounded-full px-2 py-1 text-xs font-medium ${chipClasses(value)}`}>
      {humanize(value)}
    </span>
  );
}
