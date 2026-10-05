import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { listIdentityCompletion } from '../api';
import { IdentityGapNotice } from '../components/IdentityGapNotice';
import type { IdentityCompletionItem } from '../types';

import { IdentityCompletionPage } from './IdentityCompletionPage';

vi.mock('../api', () => ({ listIdentityCompletion: vi.fn() }));

function item(overrides: Partial<IdentityCompletionItem> = {}): IdentityCompletionItem {
  return {
    company_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    name: 'Rotterdam Trading BV',
    country: 'NL',
    pipeline_status: 'NOT_IN_PIPELINE',
    created_via: 'DEAL_BUYER',
    missing: 'REGISTRATION_NUMBER',
    required: true,
    created_at: '2026-10-01T00:00:00Z',
    ...overrides,
  };
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <IdentityCompletionPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe('IdentityCompletionPage', () => {
  it('groups what a rule requires apart from what is only worth doing', async () => {
    vi.mocked(listIdentityCompletion).mockResolvedValue({
      items: [
        item(),
        item({
          company_id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          name: 'Chennai Spices',
          country: 'IN',
          pipeline_status: 'IN_PIPELINE',
          created_via: 'MANUAL',
          missing: 'PAN',
          required: false,
        }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    renderPage();

    const required = await screen.findByRole('region', { name: 'Required' });
    const optional = screen.getByRole('region', { name: 'Worth completing' });
    expect(within(required).getByText('Rotterdam Trading BV')).toBeInTheDocument();
    expect(within(required).getByText(/Missing: Registration number/)).toBeInTheDocument();
    expect(within(required).getByText(/Buyer only/)).toBeInTheDocument();
    expect(within(required).getByText(/Created from a deal buyer/)).toBeInTheDocument();
    expect(within(optional).getByText(/Missing: PAN/)).toBeInTheDocument();
    // Each row opens the company, where the edit that completes it lives.
    expect(within(required).getByRole('link')).toHaveAttribute(
      'href',
      '/companies/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    );
  });

  it('says so when every company can be identified', async () => {
    vi.mocked(listIdentityCompletion).mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    renderPage();
    expect(await screen.findByText(/Every company the CRM holds can be identified/)).toBeInTheDocument();
  });

  it('shows a load failure as one', async () => {
    vi.mocked(listIdentityCompletion).mockRejectedValue(new ApiError(500, 'boom'));
    renderPage();
    expect(await screen.findByText(/Couldn't load the companies to complete/)).toBeInTheDocument();
  });
});

describe('IdentityGapNotice', () => {
  it('asks a foreign company for its registration number, as the CRM requires', () => {
    render(<IdentityGapNotice country="NL" canEdit />);
    const notice = screen.getByTestId('identity-gap-notice');
    expect(notice).toHaveTextContent(/registration number its own registrar issued/);
    expect(notice).toHaveTextContent(/required for a company outside India/);
    expect(notice).toHaveTextContent(/Add it with Edit/);
  });

  it('asks an Indian company for a PAN without calling it required', () => {
    render(<IdentityGapNotice country="IN" canEdit />);
    expect(screen.getByTestId('identity-gap-notice')).toHaveTextContent(/not required/);
  });

  it('offers no edit to a role that cannot edit', () => {
    render(<IdentityGapNotice country="NL" canEdit={false} />);
    expect(screen.getByTestId('identity-gap-notice')).not.toHaveTextContent(/Add it with Edit/);
  });
});
