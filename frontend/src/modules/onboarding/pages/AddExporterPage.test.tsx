import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { createExporterLead } from '../api';

import { AddExporterPage } from './AddExporterPage';

// Hoisted above the imports by vitest, so the page's hook gets the mock.
vi.mock('../api', () => ({ createExporterLead: vi.fn() }));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <AddExporterPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('AddExporterPage — the company identity (L2-03)', () => {
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
});
