import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';
import { useCurrentUser } from '@/platform/auth';

import {
  getDocumentCategories,
  listDealRequiredDocuments,
  setDealRequiredDocument,
} from '../api';
import type {
  DealRequiredDocument,
  DealRequiredDocuments,
  DocumentCategoryList,
} from '../types';

import { DealRequiredDocumentsPage } from './DealRequiredDocumentsPage';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({
  getDocumentCategories: vi.fn(),
  listDealRequiredDocuments: vi.fn(),
  setDealRequiredDocument: vi.fn(),
}));

/** The deal's filing catalogue, as `GET /documents/categories?owner=DEAL` serves it. */
const CATALOGUE: DocumentCategoryList = {
  scanner_name: 'pass-through',
  categories: [
    {
      category: 'PRE_SHIPMENT',
      owner_kind: 'DEAL',
      types: [
        { key: 'proforma_invoice', label: 'Proforma invoice' },
        { key: 'purchase_order', label: 'Purchase order' },
      ],
    },
    {
      category: 'SHIPPING',
      owner_kind: 'DEAL',
      types: [
        { key: 'bill_of_lading', label: 'Bill of lading' },
        { key: 'packing_list', label: 'Packing list' },
      ],
    },
  ],
};

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
  vi.mocked(getDocumentCategories).mockResolvedValue(CATALOGUE);
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

  // Who may open this screen is decided at the route now: any other role
  // gets the generic NotFound and never loads the page. That is asserted, role by
  // role, in `src/routes/access.matrix.test.tsx`, which replaces the in-page
  // "Administrators only" checks that used to be here.

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

  it('offers only the types the settings configure for the chosen category', async () => {
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Require a category/ }));
    const typeSelect = screen.getByLabelText(/Document type/);
    // Nothing to choose until a category is: a type belongs to one category.
    expect(typeSelect).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/Category/), {
      target: { value: 'SHIPPING' },
    });
    await waitFor(() =>
      expect(within(typeSelect).getByRole('option', { name: 'Bill of lading' })).toBeInTheDocument(),
    );
    expect(within(typeSelect).getAllByRole('option').map((o) => o.textContent)).toEqual([
      'Any type in the category',
      'Bill of lading',
      'Packing list',
    ]);
  });

  it('sends a named type when one is chosen', async () => {
    vi.mocked(setDealRequiredDocument).mockResolvedValue(
      requirement({ category: 'SHIPPING', document_type: 'bill_of_lading' }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Require a category/ }));
    fireEvent.change(screen.getByLabelText(/Category/), {
      target: { value: 'SHIPPING' },
    });
    const typeSelect = screen.getByLabelText(/Document type/);
    await waitFor(() =>
      expect(within(typeSelect).getByRole('option', { name: 'Bill of lading' })).toBeInTheDocument(),
    );
    fireEvent.change(typeSelect, { target: { value: 'bill_of_lading' } });
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

  it('lists every deal category, and opens Require on the one chosen', async () => {
    renderPage();
    await screen.findByTestId('requirement-row');
    const categories = screen.getByRole('list', { name: 'Deal document categories' });
    expect(within(categories).getAllByTestId('category-row')).toHaveLength(7);
    // Pre-shipment is required for any type, so it offers no second "Require".
    expect(
      screen.queryByRole('button', { name: /^Require Pre-shipment/ }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /^Require Shipping/ }));
    expect(await screen.findByLabelText(/Category/)).toHaveValue('SHIPPING');
  });

  it('says someone else changed it when the server reports the race', async () => {
    vi.mocked(setDealRequiredDocument).mockRejectedValue(
      new ApiError(409, 'The requirement changed.', 'DEAL_REQUIRED_DOCUMENT_CHANGED'),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: /Require a category/ }));
    fireEvent.change(screen.getByLabelText(/Category/), { target: { value: 'BUYER' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add requirement' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Someone else changed this requirement first/,
    );
  });

  it('never offers an edit or a delete', async () => {
    renderPage();
    await screen.findByTestId('requirement-row');

    for (const name of [/^Edit/, /^Delete/, /^Remove$/]) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
  });
});
