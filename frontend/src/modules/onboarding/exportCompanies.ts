/**
 * The Companies list as a CSV, built in the browser from the rows already on screen.
 *
 * There is no export route on the server, so this exports **what the list is currently
 * showing** — the filters in force, up to the number already loaded. That is a real
 * limit, not a detail: the button says how many rows it will write so nobody believes
 * they have exported a database when they have exported a page of it.
 *
 * **The columns are chosen, not fixed.** Sales wants who and where; operations wants the
 * checks and the paperwork. Rather than one file holding everything, the picker writes
 * the columns asked for, in the order below — so two teams get two files and neither
 * reads past columns it does not want.
 *
 * **Identifiers are written exactly as the server sent them.** PAN, GSTIN, IEC, CIN and
 * the registration number reach the browser masked for every role but COMPLIANCE and
 * ADMIN. So the same export run by two people holds different values — bullets for one,
 * real tax numbers for the other. That is the masking rule working, not a leak: nothing
 * here can reveal what the server withheld. It does mean an export is as sensitive as
 * whoever produced it.
 */

import type {
  BackgroundCheckState,
  CompanyTradeRole,
  ExporterProfileListItem,
} from './types';

/** Words rather than the enum, since these columns are read by people, not parsed. */
const TRADE_ROLE_LABEL: Record<CompanyTradeRole, string> = {
  SELLER: 'Seller',
  BUYER: 'Buyer',
  BOTH: 'Both',
};

const CHECK_LABEL: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'Not started',
  IN_REVIEW: 'In review',
  CLEAR: 'Clear',
  MORE_INFO: 'More information needed',
  FLAGGED: 'Flagged',
  ON_HOLD: 'On hold',
};

/** A list of values as one cell, so a company's three markets stay in one column. */
const joined = (values: readonly string[] | null | undefined): string | null =>
  values && values.length > 0 ? values.join('; ') : null;

/** A timestamp as a plain date — the part anyone reads in a spreadsheet. */
const day = (value: string | null | undefined): string | null => value?.slice(0, 10) ?? null;

export interface ExportColumn {
  /** Stable across renames of the heading: it is what a remembered choice stores. */
  id: string;
  heading: string;
  /** Which group it appears under in the picker. */
  group: 'Company' | 'Identifiers' | 'Trade' | 'Status' | 'Dates';
  read: (profile: ExporterProfileListItem) => string | null;
}

/**
 * Every column that can be exported, in the order a chosen file writes them.
 *
 * Only what the list row actually carries. Nothing is derived from a second request:
 * a column that needed one would make an export a few hundred round trips.
 */
export const EXPORT_COLUMNS: readonly ExportColumn[] = [
  { id: 'name', heading: 'Company', group: 'Company', read: (p) => p.name },
  { id: 'country', heading: 'Country', group: 'Company', read: (p) => p.country },
  { id: 'industry', heading: 'Industry', group: 'Company', read: (p) => p.industry },
  {
    id: 'year_established',
    heading: 'Year established',
    group: 'Company',
    read: (p) => (p.year_established == null ? null : String(p.year_established)),
  },
  {
    id: 'owner',
    heading: 'Owner',
    group: 'Company',
    read: (p) => p.relationship_manager_name ?? p.relationship_manager,
  },
  { id: 'source', heading: 'Source', group: 'Company', read: (p) => p.source },

  { id: 'pan', heading: 'PAN', group: 'Identifiers', read: (p) => p.pan },
  { id: 'iec', heading: 'IEC', group: 'Identifiers', read: (p) => p.iec },
  { id: 'cin', heading: 'CIN', group: 'Identifiers', read: (p) => p.cin },
  {
    id: 'registration_number',
    heading: 'Registration number',
    group: 'Identifiers',
    read: (p) => p.registration_number,
  },
  {
    id: 'gstins',
    heading: 'GST registrations',
    group: 'Identifiers',
    read: (p) => joined(p.gstins),
  },

  {
    id: 'export_markets',
    heading: 'Export markets',
    group: 'Trade',
    read: (p) => joined(p.export_markets),
  },
  { id: 'products', heading: 'Products', group: 'Trade', read: (p) => joined(p.products) },
  {
    id: 'trade_role',
    heading: 'Seller/Buyer',
    group: 'Trade',
    read: (p) => (p.trade_role ? TRADE_ROLE_LABEL[p.trade_role] : null),
  },

  { id: 'journey', heading: 'Journey', group: 'Status', read: (p) => p.journey },
  { id: 'qualification', heading: 'Qualification', group: 'Status', read: (p) => p.qualification },
  {
    id: 'background_check',
    heading: 'Background check',
    group: 'Status',
    read: (p) => (p.background_check ? CHECK_LABEL[p.background_check] : null),
  },
  { id: 'marker', heading: 'Relationship', group: 'Status', read: (p) => p.marker },
  { id: 'pipeline_status', heading: 'Pipeline', group: 'Status', read: (p) => p.pipeline_status },

  { id: 'created_at', heading: 'Created', group: 'Dates', read: (p) => day(p.created_at) },
  { id: 'updated_at', heading: 'Last updated', group: 'Dates', read: (p) => day(p.updated_at) },
];

/**
 * What a first-time export writes: who the company is and where it has got to.
 *
 * Not every column. An export nobody narrowed should still be readable, and a
 * twenty-column sheet is not — the identifiers and the trade detail are a deliberate
 * choice, so they start unticked.
 */
export const DEFAULT_COLUMN_IDS: readonly string[] = [
  'name',
  'country',
  'industry',
  'owner',
  'journey',
  'qualification',
  'marker',
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

/**
 * `profiles` as CSV text, header first, holding only the chosen columns.
 *
 * The order is `EXPORT_COLUMNS`', not the order they were ticked: a file whose columns
 * moved about depending on which box was clicked first cannot be compared with last
 * month's. An id that no longer exists is ignored rather than written as a blank column.
 */
export function companiesToCsv(
  profiles: readonly ExporterProfileListItem[],
  columnIds: readonly string[] = DEFAULT_COLUMN_IDS,
): string {
  const chosen = new Set(columnIds);
  const columns = EXPORT_COLUMNS.filter((column) => chosen.has(column.id));
  const header = columns.map((column) => field(column.heading)).join(',');
  const rows = profiles.map((profile) =>
    columns.map((column) => field(column.read(profile))).join(','),
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

/**
 * How many rows one export may gather, and how many it asks for at a time.
 *
 * The list route caps a single request at 200, so an export of the whole filtered list
 * is several requests. `EXPORT_MAX_ROWS` stops that becoming hundreds of them on a
 * careless unfiltered export; past it the file holds the first `EXPORT_MAX_ROWS` rows
 * and the caller says so rather than pretending it is everything.
 */
export const EXPORT_PAGE = 200;
export const EXPORT_MAX_ROWS = 5000;

/**
 * Every company matching these filters, not just the page on screen.
 *
 * The screen loads 50 at a time; exporting what happened to be loaded is how an export
 * of 208 companies quietly becomes a file of 50. This asks again, in pages, until a
 * short page says there are no more.
 *
 * `fetchPage` is the list call itself, passed in so this stays a plain function: the
 * page already knows the filters in force, and this should not rebuild them.
 */
export async function gatherForExport<T>(
  fetchPage: (limit: number, offset: number) => Promise<readonly T[]>,
  { maxRows = EXPORT_MAX_ROWS, page = EXPORT_PAGE } = {},
): Promise<{ rows: T[]; capped: boolean }> {
  const rows: T[] = [];
  for (let offset = 0; offset < maxRows; offset += page) {
    const batch = await fetchPage(Math.min(page, maxRows - offset), offset);
    rows.push(...batch);
    // A short page is the end of the list; the route has no total to ask for.
    if (batch.length < page) return { rows, capped: false };
  }
  return { rows, capped: true };
}
