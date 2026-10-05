/** The identifier lookup's detection (frontend-plan §8.4): what a typed value looks like. */

export type EntryKind = 'PAN' | 'GSTIN' | 'IEC' | 'CIN' | 'name';

const PAN = /^[A-Z]{5}[0-9]{4}[A-Z]$/;
const GSTIN = /^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/;
const IEC = /^[0-9]{10}$/;
const CIN = /^[LU][0-9]{5}[A-Z]{2}[0-9]{4}[A-Z]{3}[0-9]{6}$/;

/** What `text` looks like. A shape, not a validation: the server decides. */
export function detectEntry(text: string): { kind: EntryKind; value: string; pan?: string } {
  const value = text.trim().toUpperCase().replace(/\s+/g, '');
  if (PAN.test(value)) return { kind: 'PAN', value, pan: value };
  if (GSTIN.test(value)) return { kind: 'GSTIN', value, pan: value.slice(2, 12) };
  if (IEC.test(value)) return { kind: 'IEC', value };
  if (CIN.test(value)) return { kind: 'CIN', value };
  return { kind: 'name', value: text.trim() };
}
