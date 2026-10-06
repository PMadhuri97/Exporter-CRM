/**
 * A status, risk or verdict tag for the verification workspace.
 * Shows the server's value, humanized; the colour is from
 * `chipClasses`.
 */

import { humanize } from '@/lib/format';

import { chipClasses } from './verification-labels';

export function VerificationStatusChip({ value }: { value: string }) {
  return (
    <span className={`inline-flex rounded-sm px-1.5 py-0.5 text-caption font-medium ${chipClasses(value)}`}>
      {humanize(value)}
    </span>
  );
}
