/**
 * The Companies list as a CSV, built in the browser from the rows already on screen.
 *
 * There is no export route on the server, so this exports **what the list is currently
 * showing** — the filters in force, up to the number already loaded. That is a real
 * limit, not a detail: the button says how many rows it will write so nobody believes
 * they have exported a database when they have exported a page of it.
 *
 * **Identifiers are included, exactly as the server sent them.** PAN, GSTIN, IEC, CIN
 * and the registration number reach the browser masked for every role but COMPLIANCE
 * and ADMIN, and this writes what it was given. So the same export run by two people
 * holds different values — bullets for one, real tax numbers for the other. That is the
 * masking rule working, not a leak: nothing here can reveal what the server withheld.
 * It does mean an export is as sensitive as whoever produced it.
 */

import type { CompanyTradeRole, ExporterProfileListItem } from './types';

/** Words rather than the enum, since this column is read by people, not parsed. */
const TRADE_ROLE_LABEL: Record<CompanyTradeRole, string> = {
  SELLER: 'Seller',
  BUYER: 'Buyer',
  BOTH: 'Both',
};

/** A list of values as one cell, so a company's three markets stay in one column. */
const joined = (values: readonly string[] | null | undefined): string | null =>
  values && values.length > 0 ? values.join('; ') : null;

/** A timestamp as a plain date — the part anyone reads in a spreadsheet. */
const day = (value: string | null | undefined): string | null => value?.slice(0, 10) ?? null;

/**
 * The columns, in order, and how each is read from a row.
 *
 * It follows the company record's own reading order — who they are, how to identify
 * them, what they trade, then where they have got to — so somebody with the export open
 * beside the screen is looking at the same thing in the same order.
 */
const COLUMNS: readonly [string, (profile: ExporterProfileListItem) => string | null][] = [
  ['Company', (p) => p.name],
  ['Country', (p) => p.country],
  ['PAN', (p) => p.pan],
  ['IEC', (p) => p.iec],
  ['CIN', (p) => p.cin],
  ['Registration number', (p) => p.registration_number],
  ['GST registrations', (p) => joined(p.gstins)],
  ['Industry', (p) => p.industry],
  ['Export markets', (p) => joined(p.export_markets)],
  ['Products', (p) => joined(p.products)],
  ['Year established', (p) => (p.year_established == null ? null : String(p.year_established))],
  ['Owner', (p) => p.relationship_manager],
  ['Source', (p) => p.source],
  ['Journey', (p) => p.journey],
  ['Qualification', (p) => p.qualification],
  ['Relationship', (p) => p.marker],
  // Which side the company has actually traded on, not whether anyone put it in the
  // pipeline. Empty where it has done neither — "no deals yet" is not a third role.
  ['Seller/Buyer', (p) => (p.trade_role ? TRADE_ROLE_LABEL[p.trade_role] : null)],
  ['Created', (p) => day(p.created_at)],
  ['Last updated', (p) => day(p.updated_at)],
];

/**
 * One CSV field: quoted when it has to be, and defused when it looks like a formula.
 *
 * A value starting `=`, `+`, `-` or `@` is executed by Excel and Sheets when the file is
 * opened — a company named `=HYPERLINK(...)` would run on the machine of whoever opened
 * the export. Prefixing an apostrophe is the usual defence: the spreadsheet shows the
 * text and runs nothing.
 */
function field(value: string | null): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  const safe = /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
  return /[",\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

/** `profiles` as CSV text, header row first. */
export function companiesToCsv(profiles: readonly ExporterProfileListItem[]): string {
  const header = COLUMNS.map(([name]) => field(name)).join(',');
  const rows = profiles.map((profile) =>
    COLUMNS.map(([, read]) => field(read(profile))).join(','),
  );
  // CRLF: the line ending the CSV format names, and the one Excel is happiest with.
  return [header, ...rows].join('\r\n');
}

/** `companies-2026-10-08.csv` — dated, so two exports do not overwrite each other. */
export function csvFileName(now: Date = new Date()): string {
  const pad = (value: number) => String(value).padStart(2, '0');
  return `companies-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}.csv`;
}

/**
 * The bytes a browser will save. A UTF-8 byte-order mark goes first: without it Excel
 * on Windows reads the file as the local code page and turns every accented company
 * name into mojibake.
 */
export function csvBlob(text: string): Blob {
  return new Blob([`\ufeff${text}`], { type: 'text/csv;charset=utf-8' });
}
