import type { ComplianceWorkItem } from '../types';

/** "3h", "2d", "just now" — how long since `iso`, in wall-clock time. */
export function waitedFor(iso: string, now: Date = new Date()): string {
  const minutes = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 60_000));
  if (minutes < 2) return 'just now';
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

export const STAGE_LABEL: Record<ComplianceWorkItem['stage'], string> = {
  review: 'In review',
  info: 'Waiting on information',
  approval: 'Awaiting approval',
};
