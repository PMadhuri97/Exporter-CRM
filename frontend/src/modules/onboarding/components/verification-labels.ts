/**
 * Words, colours and option lists for verification results — **owner: Developer 4B**.
 *
 * Nothing here decides what a user may do. Who may record or review a result comes
 * from the server's `capabilities`, never from a role comparison (4b-task.md §5.10).
 * `humanize` and `formatDateTime` are the app's own (`@/lib/format`).
 */

import type {
  VerificationResult,
  VerificationResultStatus,
  VerificationReviewStatus,
  VerificationRiskLevel,
  VerificationType,
} from '../types';

/**
 * The company check types the Company tab is scoped to, and the types a manual result
 * on the company may be recorded as. Every one is a valid check on an EXPORTER subject
 * on the server (`verification_service._VALID_ENTITY_TYPES_FOR_CHECK`); the server
 * still refuses a pair it cannot interpret, so this only narrows the form.
 */
export const COMPANY_CHECK_TYPES: VerificationType[] = [
  'KYB',
  'COMPANY_REGISTRY',
  'GST',
  'IEC',
  'UBO',
  'AML',
  'CFT',
  'SANCTIONS',
  'PEP',
  'ADVERSE_MEDIA',
];

/** The check types offered for a deal's buyer — all valid on a BUYER subject. */
export const BUYER_CHECK_TYPES: VerificationType[] = [
  'BUYER',
  'KYB',
  'COMPANY_REGISTRY',
  'SANCTIONS',
  'AML',
  'PEP',
  'ADVERSE_MEDIA',
];

/** A manual result is recorded with its real outcome; `PENDING` is refused (§5.9). */
export const MANUAL_OUTCOMES: VerificationResultStatus[] = ['PASSED', 'FAILED', 'REVIEW'];
export const RISK_LEVELS: VerificationRiskLevel[] = ['LOW', 'MEDIUM', 'HIGH', 'CRITICAL'];
export const REVIEW_OUTCOMES: VerificationReviewStatus[] = ['ACCEPTED', 'REJECTED', 'ESCALATED'];

export function chipClasses(value: string): string {
  // CRITICAL is a solid fill rather than another tinted pill: it has to read as a
  // different *class* of signal at a glance, not as a slightly darker HIGH.
  if (value === 'CRITICAL') return 'bg-red-600 text-white';
  if (['PASSED', 'LOW', 'ACCEPTED', 'CLOSED'].includes(value)) return 'bg-emerald-50 text-emerald-700';
  if (['FAILED', 'HIGH', 'REJECTED'].includes(value)) return 'bg-red-50 text-red-700';
  if (['REVIEW', 'MEDIUM', 'ESCALATED', 'NEEDS_REVIEW', 'OPEN'].includes(value)) return 'bg-amber-50 text-amber-700';
  return 'bg-surface-sunken text-ink-muted';
}

/**
 * Where a result came from, said honestly. `provenance` is served by the backend:
 * `MANUAL` is a person; `STUB` is the RXIL stub — not RXIL, whose results contract
 * (D12) is unpublished; `PROVIDER` is a real integration, shown by its stored name.
 */
export function provenanceLabel(result: Pick<VerificationResult, 'provenance' | 'provider'>): string {
  if (result.provenance === 'MANUAL') return 'Manual (person)';
  if (result.provenance === 'STUB') return 'RXIL stub, not RXIL';
  return result.provider.toUpperCase();
}

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/**
 * A reviewer is stored as a user id, and no endpoint resolves another user's id to
 * a name, so an id is shortened and labelled rather than shown raw.
 */
export function formatReviewer(value: string | null | undefined): string {
  if (!value) return '—';
  if (UUID_PATTERN.test(value)) return `User ${value.slice(0, 8)}…`;
  return value;
}

/**
 * Whether a `url` evidence reference is a web link that is safe to render as `href`:
 * an absolute `http:` or `https:` URL with a host. React 18 does not block a
 * `javascript:` href, so anything else — including a row stored before the server
 * refused it — is shown as text, never as a link. Same rule as the server's
 * `verification_evidence.check_evidence_shape`.
 */
export function isWebLink(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:') && url.host !== '';
  } catch {
    return false;
  }
}
