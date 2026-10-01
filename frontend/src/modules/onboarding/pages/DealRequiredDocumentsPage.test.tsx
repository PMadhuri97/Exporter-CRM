import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { listDealRequiredDocuments, setDealRequiredDocument } from '../api';
import type { DealRequiredDocument, DealRequiredDocuments } from '../types';

import { DealRequiredDocumentsPage } from './DealRequiredDocumentsPage';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({
  listDealRequiredDocuments: vi.fn(),
  setDealRequiredDocument: vi.fn(),
}));

function requirement(
  overrides: Partial<DealRequiredDocument> = {},
): DealRequiredDocument {
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    category: 'PRE_SHIPMENT',
    document_type: null,
    version: 1,
    active: true,
    created_by: null,
    created_at: '2026-10-01T09:00:00Z',
    ...overrides,
  };
}

function rule(overrides: Partial<DealRequiredDocuments> = {}): DealRequiredDocuments {
  return {
    requirements: [requirement()],
    history: [requirement()],
    can_edit: true,
    ...overrides,
  };
}

function signedInAs(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 'user-1',
    email: 'me@aner.example',
    full_name: 'Me',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <DealRequiredDocumentsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  signedInAs('ADMIN');
  vi.mocked(listDealRequiredDocuments).mockResolvedValue(rule());
  vi.mocked(setDealRequiredDocument).mockResolvedValue(
    requirement({ version: 2, active: false }),
  );
});

describe('DealRequiredDocumentsPage', () => {
  it('shows the seeded requirement, and says nobody added it', async () => {
    renderPage();

    const row = await screen.findByTestId('requirement-row');
    expect(within(row).getByText(/Pre-shipment/)).toBeInTheDocument();
    expect(within(row).getByText('Required')).toBeInTheDocument();
  });

  it('is refused to anyone but an administrator', async () => {
    for (const role of ['OPERATIONS', 'COMPLIANCE', 'DEVELOPER']) {
      signedInAs(role);
      const { unmount } = renderPage();
      expect(await screen.findByText('Administrators only')).toBeInTheDocument();
      // No controls, and nothing from the rule leaks into the refusal.
      expect(screen.queryByTestId('requirement-row')).not.toBeInTheDocument();
      expect(
        screen.queryByRole('button', { name: /Require a category/ }),
      ).not.toBeInTheDocument();
      unmount();
    }
  });

  it('stops requiring a category by writing a version, never a delete', async () => {
    renderPage();

    const row = await screen.findByTestId('requirement-row');
    fireEvent.click(within(row).getByRole('button', { name: 'Stop requiring' }));

    await waitFor(() => expect(setDealRequiredDocument).toHaveBeenCalled());
    expect(vi.mocked(setDealRequiredDocument).mock.calls[0]?.[0]).toEqual({
      category: 'PRE_SHIPMENT',
      document_type: null,
      active: false,
    });
  });

  it('offers no way to remove a requirement that is already removed', async () => {
    vi.mocked(listDealRequiredDocuments).mockResolvedValue(
      rule({ requirements: [requirement({ version: 2, active: false })] }),
    );
    renderPage();

    const row = await screen.findByTestId('requirement-row');
    expect(within(row).getByText('Not required')).toBeInTheDocument();
    expect(
      within(row).queryByRole('button', { name: 'Stop requiring' }),
    ).not.toBeInTheDocument();
  });

  it('adds a requirement, sending null for "any type"', async () => {
    vi.mocked(setDealRequiredDocument).mockResolvedValue(
      requirement({ category: 'BUYER' }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Require a category/ }));
    fireEvent.change(screen.getByLabelText(/Category/), { target: { value: 'BUYER' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));

    await waitFor(() => expect(setDealRequiredDocument).toHaveBeenCalled());
    expect(vi.mocked(setDealRequiredDocument).mock.calls[0]?.[0]).toEqual({
      category: 'BUYER',
      // Not `''`: the sentinel is the database's business, never the client's.
      document_type: null,
      active: true,
    });
  });

  it('sends a named type when one is given', async () => {
    vi.mocked(setDealRequiredDocument).mockResolvedValue(
      requirement({ category: 'SHIPPING', document_type: 'bill_of_lading' }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Require a category/ }));
    fireEvent.change(screen.getByLabelText(/Category/), {
      target: { value: 'SHIPPING' },
    });
    fireEvent.change(screen.getByLabelText(/Document type/), {
      target: { value: '  bill_of_lading  ' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));

    await waitFor(() => expect(setDealRequiredDocument).toHaveBeenCalled());
    expect(vi.mocked(setDealRequiredDocument).mock.calls[0]?.[0]).toEqual({
      category: 'SHIPPING',
      document_type: 'bill_of_lading',
      active: true,
    });
  });

  it('shows the server refusal as the server worded it', async () => {
    vi.mocked(setDealRequiredDocument).mockRejectedValue(
      new Error('ENTITY_KYC is filed against a company, not a deal'),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Require a category/ }));
    fireEvent.change(screen.getByLabelText(/Category/), { target: { value: 'BUYER' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));

    expect(
      await screen.findByText(/filed against a company, not a deal/),
    ).toBeInTheDocument();
  });

  it('never offers an edit or a delete', async () => {
    renderPage();
    await screen.findByTestId('requirement-row');

    for (const name of [/^Edit/, /^Delete/, /^Remove$/]) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
  });
});
