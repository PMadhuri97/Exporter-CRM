import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { importCompanies } from '../api';

import { CompanyImportPage } from './CompanyImportPage';

vi.mock('../api', () => ({ importCompanies: vi.fn(), getCompanyImportTemplate: vi.fn() }));

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

describe('CompanyImportPage — bulk CSV import (L2-13, L2-14)', () => {
  beforeEach(() => {
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
    fireEvent.change(screen.getByLabelText('CSV file'), { target: { files: [file] } });
    fireEvent.click(submit);

    await waitFor(() => expect(importCompanies).toHaveBeenCalledWith(file));
    expect(await screen.findByTestId('import-summary')).toHaveTextContent(
      '3 rows · 1 created · 0 matched · 1 rejected · 1 possible duplicates',
    );
    expect(screen.getByText('PAN is not in the right format')).toBeInTheDocument();
    expect(screen.getByText('Resembles an existing company')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Candidate 1' })).toHaveAttribute(
      'href',
      '/exporters/22222222-2222-4222-8222-222222222222',
    );
  });
});
