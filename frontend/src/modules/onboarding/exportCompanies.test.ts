import { describe, expect, it } from 'vitest';

import {
  companiesToCsv,
  csvFileName,
  DEFAULT_COLUMN_IDS,
  EXPORT_COLUMNS,
  gatherForExport,
} from './exportCompanies';
import type { ExporterProfileListItem } from './types';

/** The CSV's own line ending, as a pattern — so these tests need no escaped strings. */
const LINES = /\r?\n/;

/** Every column, for the tests that care about the whole row. */
const ALL = EXPORT_COLUMNS.map((column) => column.id);

const row = (over: Partial<ExporterProfileListItem>): ExporterProfileListItem =>
  ({
    customer_id: 'c1',
    name: 'Acme Exports',
    country: 'IN',
    // Masked, as the server sends it to every role but COMPLIANCE and ADMIN.
    pan: '••••••234F',
    iec: '1234567890',
    cin: null,
    registration_number: null,
    gstins: ['27ABCDE1234F1Z5', '33ABCDE1234F1Z9'],
    industry: 'Textiles',
    export_markets: ['US', 'GB'],
    products: ['Garments'],
    year_established: 2019,
    relationship_manager: 'Jane RM',
    relationship_manager_name: 'Jane RM',
    source: 'SALES',
    journey: 'LEAD',
    qualification: 'NOT_YET_REVIEWED',
    marker: 'NONE',
    pipeline_status: 'IN_PIPELINE',
    trade_role: 'SELLER',
    background_check: 'CLEAR',
    date_added: '2026-01-02T03:04:05Z',
    created_at: '2026-01-02T03:04:05Z',
    updated_at: '2026-03-04T05:06:07Z',
    ...over,
  }) as ExporterProfileListItem;

/** The cells of the one data row, for the chosen columns. */
const cells = (profile: ExporterProfileListItem, ids: readonly string[] = ALL) =>
  companiesToCsv([profile], ids).split(LINES)[1]?.split(',');

/** What the file calls each column, in the order it writes them. */
const headings = (ids: readonly string[]) => companiesToCsv([], ids).split(LINES)[0]?.split(',');

describe('companiesToCsv — choosing columns', () => {
  it('writes only the columns asked for', () => {
    const [header, line] = companiesToCsv([row({})], ['name', 'country']).split(LINES);
    expect(header).toBe('Company,Country');
    expect(line).toBe('Acme Exports,IN');
  });

  it('writes them in the catalogue’s order, not the order they were ticked', () => {
    // A file whose columns moved about depending on which box was clicked first could
    // not be compared with last month's.
    expect(headings(['updated_at', 'name', 'pan'])).toEqual(['Company', 'PAN', 'Last updated']);
  });

  it('ignores an id that no longer exists rather than writing a blank column', () => {
    expect(headings(['name', 'turnover', 'country'])).toEqual(['Company', 'Country']);
  });

  it('defaults to a readable set, not every column', () => {
    const [header] = companiesToCsv([row({})]).split(LINES);
    expect(header).toBe(
      EXPORT_COLUMNS.filter((column) => DEFAULT_COLUMN_IDS.includes(column.id))
        .map((column) => column.heading)
        .join(','),
    );
    expect(DEFAULT_COLUMN_IDS.length).toBeLessThan(EXPORT_COLUMNS.length);
  });

  it('keeps every default pointing at a column that exists', () => {
    for (const id of DEFAULT_COLUMN_IDS) {
      expect(ALL).toContain(id);
    }
  });
});

describe('companiesToCsv — the values', () => {
  const at = (profile: ExporterProfileListItem, id: string) => {
    const index = EXPORT_COLUMNS.findIndex((column) => column.id === id);
    return cells(profile)?.[index];
  };

  it('writes an identifier exactly as the server sent it, masked or not', () => {
    // The export cannot reveal what the server withheld: a masked role's file holds the
    // bullets it was given, and nothing here reconstructs the value.
    expect(at(row({}), 'pan')).toBe('••••••234F');
    expect(at(row({ pan: 'ABCDE1234F' }), 'pan')).toBe('ABCDE1234F');
  });

  it('keeps a list of values in one cell', () => {
    expect(at(row({ export_markets: ['US', 'GB', 'AE'] }), 'export_markets')).toBe('US; GB; AE');
  });

  it('writes the trade role and the check in words', () => {
    expect(at(row({ trade_role: 'BOTH' }), 'trade_role')).toBe('Both');
    expect(at(row({ background_check: 'MORE_INFO' }), 'background_check')).toBe(
      'More information needed',
    );
  });

  it('leaves a value empty rather than writing "null" or a word for "none yet"', () => {
    // A company with no trade role has not been on neither side — it has no role yet,
    // which is different from having one called none.
    expect(at(row({ trade_role: null }), 'trade_role')).toBe('');
    expect(at(row({ industry: null }), 'industry')).toBe('');
    expect(cells(row({ gstins: [], export_markets: null }))?.join(',')).not.toContain('null');
  });

  it('quotes a value holding a comma, and doubles its quotes', () => {
    const [, line] = companiesToCsv([row({ name: 'Acme, "the" Exporter' })], ALL).split(LINES);
    expect(line).toContain('"Acme, ""the"" Exporter"');
  });

  it('defuses a value a spreadsheet would run as a formula', () => {
    // A company named this way would otherwise execute when the export is opened.
    const [, line] = companiesToCsv([row({ name: '=HYPERLINK("http://x","clickme")' })], ALL).split(
      LINES,
    );
    expect(line).toMatch(/^"'=HYPERLINK/);
  });

  it('dates the file so two exports do not collide', () => {
    expect(csvFileName(new Date(2026, 9, 8))).toBe('companies-2026-10-08.csv');
  });
});

describe('gatherForExport', () => {
  /** A list of `total` rows, served in pages like the real route. */
  const server = (total: number) => {
    const calls: [number, number][] = [];
    const fetchPage = (limit: number, offset: number) => {
      calls.push([limit, offset]);
      return Promise.resolve(
        Array.from({ length: Math.max(0, Math.min(limit, total - offset)) }, (_, i) => offset + i),
      );
    };
    return { calls, fetchPage };
  };

  it('keeps asking until a short page says there are no more', async () => {
    // The bug this exists for: the screen holds 50 and a 208-company export wrote 50.
    const { calls, fetchPage } = server(208);
    const { rows, capped } = await gatherForExport(fetchPage, { page: 200, maxRows: 5000 });

    expect(rows).toHaveLength(208);
    expect(capped).toBe(false);
    expect(calls).toEqual([
      [200, 0],
      [200, 200],
    ]);
  });

  it('asks once when the first page is already short', async () => {
    const { calls, fetchPage } = server(12);
    const { rows } = await gatherForExport(fetchPage, { page: 200, maxRows: 5000 });
    expect(rows).toHaveLength(12);
    expect(calls).toHaveLength(1);
  });

  it('stops at the cap and says it stopped', async () => {
    // Better a file that admits what it left out than hundreds of requests.
    const { rows, capped } = await gatherForExport(server(10_000).fetchPage, {
      page: 200,
      maxRows: 400,
    });
    expect(rows).toHaveLength(400);
    expect(capped).toBe(true);
  });

  it('never asks for more than the cap allows', async () => {
    const { calls } = server(10_000);
    const { fetchPage } = server(10_000);
    await gatherForExport((limit, offset) => {
      calls.push([limit, offset]);
      return fetchPage(limit, offset);
    }, { page: 200, maxRows: 300 });
    // The last page is trimmed so the file holds 300, not 400.
    expect(calls).toEqual([
      [200, 0],
      [100, 200],
    ]);
  });
});
