import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  addCompanyAddress,
  deactivateCompanyAddress,
  listCompanyAddresses,
  listGstRegistrations,
  setDefaultCompanyAddress,
} from '../api';
import type { CompanyAddress, GstRegistration } from '../types';

import { AddressesSection } from './AddressesSection';

vi.mock('../api', () => ({
  listCompanyAddresses: vi.fn(),
  addCompanyAddress: vi.fn(),
  updateCompanyAddress: vi.fn(),
  setDefaultCompanyAddress: vi.fn(),
  deactivateCompanyAddress: vi.fn(),
  listGstRegistrations: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const COMPANY = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function address(overrides: Partial<CompanyAddress> = {}): CompanyAddress {
  return {
    id: 'a1',
    customer_id: COMPANY,
    address_type: 'REGISTERED',
    line1: '12 Marine Drive',
    line2: null,
    city: 'Mumbai',
    state: 'Maharashtra',
    postal_code: '400001',
    country: 'IN',
    is_default: true,
    is_active: true,
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  };
}

function list(addresses: CompanyAddress[], changed = false) {
  vi.mocked(listCompanyAddresses).mockResolvedValue({
    addresses,
    last_clear_at: changed ? '2026-08-01T00:00:00Z' : null,
    registered_changed_since_clear: changed,
  });
}

function renderSection(canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AddressesSection customerId={COMPANY} canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listGstRegistrations).mockResolvedValue({ registrations: [], flagged_count: 0 });
});

describe('AddressesSection', () => {
  it('shows each address on one line with its type and default mark', async () => {
    list([address()]);
    renderSection();

    expect(
      await screen.findByText('12 Marine Drive, Mumbai, Maharashtra 400001, India'),
    ).toBeInTheDocument();
    expect(screen.getByText('Registered')).toBeInTheDocument();
    expect(screen.getByText('Default')).toBeInTheDocument();
  });

  it('keeps deactivated addresses behind "Show deactivated"', async () => {
    list([address(), address({ id: 'a2', line1: 'Old office', is_active: false, is_default: false })]);
    renderSection();
    await screen.findByText(/12 Marine Drive/);

    expect(screen.queryByText(/Old office/)).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show deactivated (1)' }));
    expect(screen.getByText(/Old office/)).toBeInTheDocument();
  });

  it('adds an address with only the fields filled in', async () => {
    list([]);
    vi.mocked(addCompanyAddress).mockResolvedValue(address());
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /Add address/ }));

    fireEvent.change(screen.getByLabelText(/^Address line 1/), { target: { value: 'Plot 7, MIDC' } });
    fireEvent.change(screen.getByLabelText(/^City/), { target: { value: 'Pune' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save address' }));

    await waitFor(() =>
      expect(addCompanyAddress).toHaveBeenCalledWith(COMPANY, {
        address_type: 'REGISTERED',
        line1: 'Plot 7, MIDC',
        line2: null,
        city: 'Pune',
        state: null,
        postal_code: null,
        country: 'IN',
        is_default: false,
        gst_registration_id: null,
      }),
    );
  });

  it('makes another address the default, and deactivates one', async () => {
    list([address(), address({ id: 'a2', line1: 'Second', is_default: false })]);
    vi.mocked(setDefaultCompanyAddress).mockResolvedValue(address({ id: 'a2' }));
    vi.mocked(deactivateCompanyAddress).mockResolvedValue(address({ is_active: false }));
    renderSection();
    await screen.findByText(/Second/);

    fireEvent.click(screen.getByRole('button', { name: 'Make default' }));
    await waitFor(() => expect(setDefaultCompanyAddress).toHaveBeenCalledWith('a2'));

    fireEvent.click(screen.getAllByRole('button', { name: 'Deactivate' })[0]!);
    await waitFor(() => expect(deactivateCompanyAddress).toHaveBeenCalledWith('a1', null));
  });

  it('offers to create an address from a GST branch and links it', async () => {
    list([]);
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [
        {
          id: 'g1',
          customer_id: COMPANY,
          gstin: '27ABCDE1234F1Z5',
          state_code: '27',
          state_name: 'Maharashtra',
          status: 'UNVERIFIED',
          address: '5th floor, Nariman Point, Mumbai',
          address_id: null,
          flag_status: 'NONE',
          flag_reason: null,
          active: true,
          deactivated_at: null,
          created_at: '2026-03-01T00:00:00Z',
          verify_url: null,
          also_held_by: [],
        } as GstRegistration,
      ],
      flagged_count: 0,
    });
    vi.mocked(addCompanyAddress).mockResolvedValue(address());
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: 'Create address' }));
    expect(screen.getByLabelText(/^Address line 1/)).toHaveValue('5th floor, Nariman Point, Mumbai');
    fireEvent.change(screen.getByLabelText(/^City/), { target: { value: 'Mumbai' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save address' }));

    await waitFor(() =>
      expect(addCompanyAddress).toHaveBeenCalledWith(
        COMPANY,
        expect.objectContaining({ state: 'Maharashtra', gst_registration_id: 'g1' }),
      ),
    );
  });

  it('says when the registered address changed after the last Clear', async () => {
    list([address()], true);
    renderSection(false);

    expect(
      await screen.findByText('The registered address changed since the last Clear.'),
    ).toBeInTheDocument();
    // A reader gets no controls.
    expect(screen.queryByRole('button', { name: /Add address/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument();
  });
});
