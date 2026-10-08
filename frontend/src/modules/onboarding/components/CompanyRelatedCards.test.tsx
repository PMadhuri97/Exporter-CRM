/**
 * The Contacts card's edit form.
 *
 * The route takes a partial body, so what matters is what the form leaves **out**: a
 * field nobody changed, and above all an email or phone that a masked role was sent as
 * bullets. Writing those back would replace the real value with `j•••@example.com`.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { updateExporterContact } from '../api';
import type { ExporterContact } from '../types';

import { CompanyRelatedCards } from './CompanyRelatedCards';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  updateExporterContact: vi.fn(),
}));
// The other three cards fetch their own lists; they are not under test here.
vi.mock('../hooks', async (importOriginal) => {
  const idle = () => ({ data: undefined, isLoading: false, isError: false });
  return {
    ...(await importOriginal<typeof import('../hooks')>()),
    useFollowUps: idle,
    useCompanyDeals: idle,
    useCompanyDocuments: idle,
  };
});

const CUSTOMER_ID = '11111111-1111-4111-8111-111111111111';

const JANE: ExporterContact = {
  id: '22222222-2222-4222-8222-222222222222',
  customer_id: CUSTOMER_ID,
  name: 'Jane Doe',
  role: 'CFO',
  email: 'jane.doe@example.com',
  phone: '+91 99999 11111',
  department: null,
  is_primary_contact: false,
};

/** What OPERATIONS is sent for the same contact: the server masks before it leaves. */
const JANE_MASKED: ExporterContact = { ...JANE, email: 'j•••@example.com', phone: '••••••••1111' };

function as(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ role } as ReturnType<typeof useCurrentUser>);
}

function renderCards(contact: ExporterContact) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyRelatedCards customerId={CUSTOMER_ID} contacts={[contact]} contactsLoading={false} canAdd />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function openEdit() {
  fireEvent.click(screen.getByRole('button', { name: 'Edit Jane Doe' }));
}

function change(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

function save() {
  fireEvent.click(screen.getByRole('button', { name: 'Save contact' }));
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(updateExporterContact).mockImplementation(async (_customer, _id, payload) => ({
    ...JANE,
    ...payload,
  }) as ExporterContact);
});

describe('Editing a contact', () => {
  it('sends only the field that changed', async () => {
    as('COMPLIANCE');
    renderCards(JANE);
    openEdit();

    change('Role / title', 'CEO');
    save();

    await waitFor(() =>
      expect(updateExporterContact).toHaveBeenCalledWith(CUSTOMER_ID, JANE.id, { role: 'CEO' }),
    );
  });

  it('clears a field that was emptied, as null', async () => {
    as('COMPLIANCE');
    renderCards(JANE);
    openEdit();

    change('Phone', '   ');
    save();

    await waitFor(() =>
      expect(updateExporterContact).toHaveBeenCalledWith(CUSTOMER_ID, JANE.id, { phone: null }),
    );
  });

  it('gives a masked role empty email and phone fields, and never sends the bullets back', async () => {
    as('OPERATIONS');
    renderCards(JANE_MASKED);
    openEdit();

    expect(screen.getByLabelText('Email')).toHaveValue('');
    expect(screen.getByLabelText('Phone')).toHaveValue('');
    expect(screen.getByLabelText('Email')).toHaveAttribute('placeholder', 'Hidden — type to replace');

    change('Department', 'Finance');
    save();

    await waitFor(() =>
      expect(updateExporterContact).toHaveBeenCalledWith(CUSTOMER_ID, JANE.id, {
        department: 'Finance',
      }),
    );
  });

  it('lets a masked role replace an email by typing a new one', async () => {
    as('OPERATIONS');
    renderCards(JANE_MASKED);
    openEdit();

    change('Email', 'jane@newco.example');
    save();

    await waitFor(() =>
      expect(updateExporterContact).toHaveBeenCalledWith(CUSTOMER_ID, JANE.id, {
        email: 'jane@newco.example',
      }),
    );
  });

  it('closes without a request when nothing changed', async () => {
    as('COMPLIANCE');
    renderCards(JANE);
    openEdit();

    save();

    await waitFor(() => expect(screen.queryByRole('button', { name: 'Save contact' })).not.toBeInTheDocument());
    expect(updateExporterContact).not.toHaveBeenCalled();
  });

  it('promotes the contact to primary', async () => {
    as('OPERATIONS');
    renderCards(JANE_MASKED);
    openEdit();

    fireEvent.click(screen.getByRole('checkbox', { name: 'Make this the primary contact' }));
    save();

    await waitFor(() =>
      expect(updateExporterContact).toHaveBeenCalledWith(CUSTOMER_ID, JANE.id, { is_primary: true }),
    );
  });

  it('will not save a contact with no name', () => {
    as('COMPLIANCE');
    renderCards(JANE);
    openEdit();

    change(/^Name/, '   ');

    expect(screen.getByRole('button', { name: 'Save contact' })).toBeDisabled();
  });
});
