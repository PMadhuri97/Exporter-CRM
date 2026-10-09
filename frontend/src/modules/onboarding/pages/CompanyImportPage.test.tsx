import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getCompanyImportTemplate, importCompanies, previewCompanyImport } from '../api';
import type { ImportPreview } from '../types';

import { CompanyImportPage } from './CompanyImportPage';

vi.mock('../api', () => ({
  importCompanies: vi.fn(),
  getCompanyImportTemplate: vi.fn(),
  previewCompanyImport: vi.fn(),
}));

const COLUMNS = ['name', 'country', 'pan', 'gstins', 'iec', 'cin', 'source', 'industry', 'registration_number'];

function preview(overrides: Partial<ImportPreview> = {}): ImportPreview {
  return {
    columns: COLUMNS,
    rows: [
      { line: 2, cells: ['Acme', 'IN', '', '27ABCDE1234F1Z5', '', '', '', 'Textiles', ''] },
    ],
    total_rows: 1,
    missing_columns: [],
    unknown_columns: [],
    duplicate_columns: [],
    max_rows: 1000,
    ready: true,
    ...overrides,
  };
}

function choose(file: File) {
  fireEvent.change(screen.getByLabelText('Import file'), { target: { files: [file] } });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyImportPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CompanyImportPage — bulk import', () => {
  beforeEach(() => {
    vi.mocked(previewCompanyImport).mockReset();
    vi.mocked(previewCompanyImport).mockResolvedValue(preview());
    vi.mocked(importCompanies).mockReset();
    vi.mocked(importCompanies).mockResolvedValue({
      total_rows: 3,
      accepted: 1,
      created: 1,
      matched: 0,
      rejected: 1,
      possible_duplicates: 1,
      rows: [
        {
          line: 2,
          status: 'accepted',
          action: 'created',
          customer_id: '11111111-1111-4111-8111-111111111111',
          reasons: [],
          warnings: [],
          candidates: [],
        },
        {
          line: 3,
          status: 'rejected',
          action: null,
          customer_id: null,
          reasons: [{ code: 'INVALID_PAN', message: 'PAN is not in the right format' }],
          warnings: [],
          candidates: [],
        },
        {
          line: 4,
          status: 'possible_duplicate',
          action: null,
          customer_id: null,
          reasons: [{ code: 'SIMILAR_NAME', message: 'Resembles an existing company' }],
          warnings: [],
          candidates: ['22222222-2222-4222-8222-222222222222'],
        },
      ],
    });
  });

  it('uploads the chosen file and shows the server report row by row', async () => {
    renderPage();
    const file = new File(['name,country\nAcme,IN\n'], 'companies.csv', { type: 'text/csv' });
    const submit = screen.getByRole('button', { name: 'Import' });
    expect(submit).toBeDisabled();
    choose(file);
    await waitFor(() => expect(submit).toBeEnabled());
    fireEvent.click(submit);

    await waitFor(() => expect(importCompanies).toHaveBeenCalledWith(file));
    expect(await screen.findByTestId('import-summary')).toHaveTextContent(
      '3 rows · 1 created · 0 matched · 1 failed · 1 possible duplicates',
    );
    const failed = screen.getByRole('group', { name: 'Failed rows' });
    expect(within(failed).getByText('Row 3')).toBeInTheDocument();
    expect(within(failed).getByText('Failed')).toBeInTheDocument();
    expect(screen.queryByText(/refused|rejected/i)).not.toBeInTheDocument();
    expect(screen.getByText('PAN is not in the right format')).toBeInTheDocument();
    expect(screen.getByText('Resembles an existing company')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Candidate 1' })).toHaveAttribute(
      'href',
      '/companies/22222222-2222-4222-8222-222222222222',
    );
  });

  it('previews the file in a grid that keeps empty cells in their own columns', async () => {
    renderPage();
    choose(new File(['x'], 'companies.xlsx'));
    const grid = await screen.findByRole('table');
    const [header, row] = within(grid).getAllByRole('row');
    expect(within(header!).getAllByRole('columnheader').map((c) => c.textContent)).toEqual(['Row', ...COLUMNS]);
    const cells = within(row!).getAllByRole('cell').map((c) => c.textContent);
    expect(cells[2]).toBe(''); // the blank PAN stays under "pan"
    expect(cells[3]).toBe('27ABCDE1234F1Z5'); // and the GSTIN under "gstins"
    expect(screen.getByText(/1 row in the file/)).toBeInTheDocument();
  });

  it('names header problems and will not import such a file', async () => {
    vi.mocked(previewCompanyImport).mockResolvedValue(
      preview({ columns: ['name', 'country', 'actor_id'], missing_columns: ['pan'], unknown_columns: ['actor_id'], ready: false }),
    );
    renderPage();
    choose(new File(['x'], 'companies.csv'));
    expect(await screen.findByText('Missing columns: pan.')).toBeInTheDocument();
    expect(screen.getByText('Not in the template: actor_id.')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
  });

  it('says a file the server cannot read is not accepted', async () => {
    vi.mocked(previewCompanyImport).mockRejectedValue(new Error('The file is not a readable Excel workbook (.xlsx)'));
    renderPage();
    choose(new File(['x'], 'companies.xlsx'));
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'File not accepted: The file is not a readable Excel workbook (.xlsx)',
    );
    expect(screen.getByRole('button', { name: 'Import' })).toBeDisabled();
  });

  it('downloads the Excel template by default and the CSV one on request', async () => {
    vi.mocked(getCompanyImportTemplate).mockResolvedValue(new Blob(['x']));
    URL.createObjectURL = vi.fn(() => 'blob:template');
    URL.revokeObjectURL = vi.fn();
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderPage();
    fireEvent.click(screen.getByRole('button', { name: 'Download template' }));
    await waitFor(() => expect(getCompanyImportTemplate).toHaveBeenCalledWith('xlsx'));
    fireEvent.click(screen.getByRole('button', { name: 'CSV template' }));
    await waitFor(() => expect(getCompanyImportTemplate).toHaveBeenCalledWith('csv'));
    await waitFor(() => expect(click).toHaveBeenCalledTimes(2));
    click.mockRestore();
  });
});
