/**
 * The Directors and owners card.
 *
 * A director or owner is a person record with roles, added through the contacts route.
 * What matters: the roles and role-only fields are sent as chosen, and a role that reads
 * the DIN, date of birth and identification number masked never sends the bullets back.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { addExporterContact, listExporterContacts, updateExporterContact } from '../api';
import type { ExporterContact } from '../types';

import { PeopleCard } from './PeopleCard';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  listExporterContacts: vi.fn(),
  addExporterContact: vi.fn(),
  updateExporterContact: vi.fn(),
}));

const CUSTOMER_ID = '11111111-1111-4111-8111-111111111111';

const CONTACT: ExporterContact = {
  id: '22222222-2222-4222-8222-222222222222',
  customer_id: CUSTOMER_ID,
  name: 'Front Desk',
  role: null,
  email: null,
  phone: null,
  department: null,
  is_primary_contact: false,
  status: 'ACTIVE',
  status_changed_at: null,
  status_reason: null,
  last_verified_at: null,
  last_verified_by: null,
  created_at: '2026-09-01T10:00:00Z',
  verification_due: false,
  is_contact: true,
  is_director: false,
  is_ubo: false,
};

const RAVI_MASKED: ExporterContact = {
  ...CONTACT,
  id: '33333333-3333-4333-8333-333333333333',
  name: 'Ravi Kumar',
  is_contact: false,
  is_director: true,
  din: '••••4567',
  date_of_birth: '••••-••-••',
  identification_type: 'PASSPORT',
  identification_number: '••••4321',
};

function as(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ role } as ReturnType<typeof useCurrentUser>);
}

function renderCard(people: ExporterContact[]) {
  vi.mocked(listExporterContacts).mockResolvedValue({ customer_id: CUSTOMER_ID, contacts: people });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PeopleCard customerId={CUSTOMER_ID} canAdd />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('Directors and owners', () => {
  it('lists directors and owners, not plain contacts', async () => {
    as('OPERATIONS');
    renderCard([CONTACT, RAVI_MASKED]);

    expect(await screen.findByText('Ravi Kumar')).toBeInTheDocument();
    expect(screen.queryByText('Front Desk')).not.toBeInTheDocument();
    expect(listExporterContacts).toHaveBeenCalledWith(CUSTOMER_ID, 'ALL');
  });

  it('adds a beneficial owner with the owner-only fields', async () => {
    as('OPERATIONS');
    vi.mocked(addExporterContact).mockResolvedValue({ ...CONTACT, is_contact: false, is_ubo: true });
    renderCard([]);
    fireEvent.click(await screen.findByRole('button', { name: 'Add' }));

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Anita Rao' } });
    fireEvent.click(screen.getByLabelText('Director'));
    fireEvent.click(screen.getByLabelText('Beneficial owner'));
    fireEvent.change(screen.getByLabelText('Ownership %'), { target: { value: '40' } });
    fireEvent.change(screen.getByLabelText('Control'), { target: { value: 'VOTING_RIGHTS' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add person' }));

    await waitFor(() => expect(addExporterContact).toHaveBeenCalled());
    const [, payload] = vi.mocked(addExporterContact).mock.calls[0]!;
    expect(payload).toMatchObject({
      name: 'Anita Rao',
      is_contact: false,
      is_director: false,
      is_ubo: true,
      din: null,
      ownership_pct: '40',
      control_type: 'VOTING_RIGHTS',
    });
  });

  it('never sends masked values back for a role that reads them masked', async () => {
    as('OPERATIONS');
    vi.mocked(updateExporterContact).mockResolvedValue(RAVI_MASKED);
    renderCard([RAVI_MASKED]);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit Ravi Kumar' }));

    expect(screen.getByLabelText(/^DIN/)).toHaveValue('');
    expect(screen.getByLabelText('Number')).toHaveValue('');
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Ravi K. Kumar' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save person' }));

    await waitFor(() =>
      expect(updateExporterContact).toHaveBeenCalledWith(CUSTOMER_ID, RAVI_MASKED.id, {
        name: 'Ravi K. Kumar',
      }),
    );
  });
});
