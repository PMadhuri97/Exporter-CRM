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

import { setExporterContactStatus, updateExporterContact } from '../api';
import type { ExporterContact } from '../types';

import { CompanyRelatedCards } from './CompanyRelatedCards';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  updateExporterContact: vi.fn(),
  setExporterContactStatus: vi.fn(),
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
  status: 'ACTIVE',
  status_changed_at: null,
  status_reason: null,
  last_verified_at: null,
  last_verified_by: null,
  created_at: '2026-09-01T10:00:00Z',
  verification_due: false,
};

const RAVI: ExporterContact = {
  ...JANE,
  id: '33333333-3333-4333-8333-333333333333',
  name: 'Ravi Kumar',
  status: 'LEFT_COMPANY',
  status_reason: 'Moved to another firm',
};

/** What OPERATIONS is sent for the same contact: the server masks before it leaves. */
const JANE_MASKED: ExporterContact = { ...JANE, email: 'j•••@example.com', phone: '••••••••1111' };

function as(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ role } as ReturnType<typeof useCurrentUser>);
}

function renderCards(contact: ExporterContact | ExporterContact[]) {
  const contacts = Array.isArray(contact) ? contact : [contact];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanyRelatedCards customerId={CUSTOMER_ID} contacts={contacts} contactsLoading={false} canAdd />
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

describe("A contact's status", () => {
  it('keeps contacts who left behind "Show inactive"', () => {
    as('COMPLIANCE');
    renderCards([JANE, RAVI]);

    expect(screen.getByText('Jane Doe')).toBeInTheDocument();
    expect(screen.queryByText('Ravi Kumar')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Show inactive (1)' }));

    expect(screen.getByText('Ravi Kumar')).toBeInTheDocument();
    expect(screen.getByText('Left company')).toBeInTheDocument();
    expect(screen.getByText('Moved to another firm')).toBeInTheDocument();
  });

  it('flags a contact whose details are due a re-check', () => {
    as('COMPLIANCE');
    renderCards({ ...JANE, verification_due: true });

    expect(screen.getByText('Verification due')).toBeInTheDocument();
  });

  it('asks for a reason before a contact can be marked as having left', async () => {
    as('COMPLIANCE');
    vi.mocked(setExporterContactStatus).mockResolvedValue({ ...JANE, status: 'LEFT_COMPANY' });
    renderCards({ ...JANE, is_primary_contact: true });
    openEdit();

    change('Status', 'LEFT_COMPANY');
    expect(screen.getByRole('button', { name: 'Save contact' })).toBeDisabled();
    expect(screen.getByRole('checkbox')).toBeDisabled();

    change(/^Reason/, 'Moved to another firm');
    save();

    await waitFor(() =>
      expect(setExporterContactStatus).toHaveBeenCalledWith(CUSTOMER_ID, JANE.id, {
        status: 'LEFT_COMPANY',
        reason: 'Moved to another firm',
      }),
    );
    // The primary flag goes with the status on the server; it is not sent separately.
    expect(updateExporterContact).not.toHaveBeenCalled();
  });
});
