import { describe, expect, it } from 'vitest';

import { companiesToCsv, csvFileName } from './exportCompanies';
import type { ExporterProfileListItem } from './types';

/** The CSV's own line ending, as a pattern — so these tests need no escaped strings. */
const LINES = /\r?\n/;

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
    source: 'SALES',
    journey: 'LEAD',
    qualification: 'NOT_YET_REVIEWED',
    marker: 'NONE',
    pipeline_status: 'IN_PIPELINE',
    trade_role: 'SELLER',
    date_added: '2026-01-02T03:04:05Z',
    created_at: '2026-01-02T03:04:05Z',
    updated_at: '2026-03-04T05:06:07Z',
    ...over,
  }) as ExporterProfileListItem;

const HEADER =
  'Company,Country,PAN,IEC,CIN,Registration number,GST registrations,Industry,' +
  'Export markets,Products,Year established,Owner,Source,Journey,Qualification,' +
  'Relationship,Seller/Buyer,Created,Last updated';

describe('companiesToCsv', () => {
  it('writes the company record’s fields, in the order the record shows them', () => {
    const lines = companiesToCsv([row({})]).split(LINES);
    expect(lines[0]).toBe(HEADER);
    expect(lines[1]).toBe(
      'Acme Exports,IN,••••••234F,1234567890,,,' +
        '27ABCDE1234F1Z5; 33ABCDE1234F1Z9,Textiles,US; GB,Garments,2019,Jane RM,SALES,' +
        'LEAD,NOT_YET_REVIEWED,NONE,Seller,2026-01-02,2026-03-04',
    );
  });

  it('writes an identifier exactly as the server sent it, masked or not', () => {
    // The export cannot reveal what the server withheld: a masked role's file holds the
    // bullets it was given, and nothing here reconstructs the value.
    const [, masked] = companiesToCsv([row({})]).split(LINES);
    expect(masked).toContain('••••••234F');

    const [, full] = companiesToCsv([row({ pan: 'ABCDE1234F' })]).split(LINES);
    expect(full).toContain('ABCDE1234F');
  });

  it('keeps a list of values in one cell', () => {
    const [, line] = companiesToCsv([row({ export_markets: ['US', 'GB', 'AE'] })]).split(LINES);
    expect(line).toContain('US; GB; AE');
  });

  it('quotes a value holding a comma, and doubles its quotes', () => {
    const [, line] = companiesToCsv([row({ name: 'Acme, "the" Exporter' })]).split(LINES);
    expect(line).toContain('"Acme, ""the"" Exporter"');
  });

  it('defuses a value a spreadsheet would run as a formula', () => {
    // A company named this way would otherwise execute when the export is opened.
    const [, line] = companiesToCsv([row({ name: '=HYPERLINK("http://x","clickme")' })]).split(
      LINES,
    );
    expect(line).toMatch(/^"'=HYPERLINK/);
  });

  it('leaves a missing value empty rather than writing "null"', () => {
    const [, line] = companiesToCsv([
      row({ industry: null, relationship_manager: null, gstins: [], export_markets: null }),
    ]).split(LINES);
    // An empty list, an absent list and an absent string all read the same: nothing.
    expect(line).not.toContain('null');
    expect(line).toBe(
      'Acme Exports,IN,••••••234F,1234567890,,,,,,Garments,2019,,SALES,' +
        'LEAD,NOT_YET_REVIEWED,NONE,Seller,2026-01-02,2026-03-04',
    );
  });

  it('dates the file so two exports do not collide', () => {
    expect(csvFileName(new Date(2026, 9, 8))).toBe('companies-2026-10-08.csv');
  });
});

describe('companiesToCsv — the trade role column', () => {
  const roleOf = (profile: ExporterProfileListItem) =>
    companiesToCsv([profile]).split(/\r?\n/)[1]?.split(',').at(-3);

  it('writes the side in words', () => {
    expect(roleOf(row({ trade_role: 'BOTH' }))).toBe('Both');
    expect(roleOf(row({ trade_role: 'BUYER' }))).toBe('Buyer');
  });

  it('leaves it empty for a company that has traded on neither side', () => {
    // Not "None": the company has no role yet, which is different from having one
    // called none.
    expect(roleOf(row({ trade_role: null }))).toBe('');
  });
});
