import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { createExporterLead } from '../api';

import { NewCompanyPanel } from './AddExporterPage';

// Hoisted above the imports by vitest, so the page's hook gets the mock.
vi.mock('../api', () => ({ createExporterLead: vi.fn(), matchCompany: vi.fn() }));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewCompanyPanel onClose={() => {}} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('New company — the company identity', () => {
  beforeEach(() => {
    vi.mocked(createExporterLead).mockReset();
    vi.mocked(createExporterLead).mockResolvedValue({
      customer_id: '11111111-1111-4111-8111-111111111111',
    } as Awaited<ReturnType<typeof createExporterLead>>);
  });

  it('does not ask the person adding a company for a contact email', () => {
    renderPage();
    expect(screen.queryByLabelText(/contact email/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/company name/i)).toBeInTheDocument();
    expect(screen.getByLabelText(/country/i)).toBeInTheDocument();
  });

  it('sends the name and the upper-cased country, and nothing about the creator', async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/company name/i), {
      target: { value: 'Acme Exports Pvt Ltd' },
    });
    fireEvent.change(screen.getByLabelText(/country/i), { target: { value: 'in' } });
    fireEvent.submit(screen.getByLabelText(/company name/i).closest('form')!);

    await waitFor(() => expect(createExporterLead).toHaveBeenCalledTimes(1));
    const [payload] = vi.mocked(createExporterLead).mock.calls[0] ?? [];
    expect(payload).toMatchObject({ name: 'Acme Exports Pvt Ltd', country: 'IN' });
    expect(payload).not.toHaveProperty('initial_user_email');
    expect(payload).not.toHaveProperty('legal_name');
    expect(payload).not.toHaveProperty('incorporation_country');
    // The journey starts at LEAD on the server; the retired lifecycle is not sent.
    expect(payload).not.toHaveProperty('lifecycle_status');
    expect(payload).not.toHaveProperty('journey');
  });

  it('starts from one smart field: a GSTIN brings its PAN into the new lead', async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/an identifier/i), { target: { value: '27aaapl1234c1zv' } });
    expect(screen.getByTestId('entry-kind')).toHaveTextContent('GSTIN');
    fireEvent.change(screen.getByLabelText(/company name/i), { target: { value: 'Lakshmi Polymers' } });
    fireEvent.change(screen.getByLabelText(/country/i), { target: { value: 'IN' } });
    fireEvent.submit(screen.getByLabelText(/company name/i).closest('form')!);
    await waitFor(() => expect(createExporterLead).toHaveBeenCalledTimes(1));
    expect(vi.mocked(createExporterLead).mock.calls[0]?.[0]).toMatchObject({
      name: 'Lakshmi Polymers',
      gstins: ['27AAAPL1234C1ZV'],
      pan: 'AAAPL1234C',
    });
  });

  it('asks a company outside India for its registration number, unless it holds a PAN', async () => {
    renderPage();
    fireEvent.change(screen.getByLabelText(/company name/i), { target: { value: 'Hanse Metall GmbH' } });
    fireEvent.change(screen.getByLabelText(/country/i), { target: { value: 'DE' } });
    expect(await screen.findByLabelText(/registration number/i)).toBeInTheDocument();
    fireEvent.submit(screen.getByLabelText(/company name/i).closest('form')!);
    expect(await screen.findByText('Required for a company outside India')).toBeInTheDocument();
    expect(createExporterLead).not.toHaveBeenCalled();
  });

  it('links to the company holding a duplicate PAN instead of printing its id', async () => {
    const holder = '597cb275-0000-4000-8000-000000000001';
    vi.mocked(createExporterLead).mockRejectedValue(
      new ApiError(
        409,
        `This PAN is already held by company ${holder}; a PAN belongs to one company only`,
        'DUPLICATE_PAN',
        null,
        { existing_customer_id: holder },
      ),
    );
    renderPage();
    fireEvent.change(screen.getByLabelText(/company name/i), { target: { value: 'Acme' } });
    fireEvent.change(screen.getByLabelText(/country/i), { target: { value: 'IN' } });
    fireEvent.submit(screen.getByLabelText(/company name/i).closest('form')!);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('This PAN is already held by another company — open it.');
    expect(alert).not.toHaveTextContent(holder);
    expect(screen.getByRole('link', { name: 'open it' })).toHaveAttribute(
      'href',
      `/companies/${holder}`,
    );
  });
});
