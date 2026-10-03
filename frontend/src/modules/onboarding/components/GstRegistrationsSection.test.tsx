import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  addGstRegistration,
  deactivateGstRegistration,
  flagGstRegistration,
  listGstRegistrations,
  unflagGstRegistration,
} from '../api';
import type { GstRegistration } from '../types';

import { GstRegistrationsSection } from './GstRegistrationsSection';

vi.mock('../api', () => ({
  listGstRegistrations: vi.fn(),
  addGstRegistration: vi.fn(),
  deactivateGstRegistration: vi.fn(),
  flagGstRegistration: vi.fn(),
  unflagGstRegistration: vi.fn(),
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn() },
}));

const COMPANY = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const OTHER = 'oooooooo-oooo-4ooo-8ooo-oooooooooooo';

function registration(overrides: Partial<GstRegistration> = {}): GstRegistration {
  return {
    id: 'rrrrrrrr-rrrr-4rrr-8rrr-rrrrrrrrrrrr',
    customer_id: COMPANY,
    gstin: '27ABCDE1234F1Z5',
    state_code: '27',
    state_name: 'Maharashtra',
    status: 'UNVERIFIED',
    address: null,
    flag_status: 'NONE',
    flag_reason: null,
    active: true,
    deactivated_at: null,
    created_at: '2026-03-01T00:00:00Z',
    verify_url: null,
    also_held_by: [],
    ...overrides,
  } as GstRegistration;
}

function renderSection({ canEdit = true, canFlag = true } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <GstRegistrationsSection customerId={COMPANY} canEdit={canEdit} canFlag={canFlag} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listGstRegistrations).mockResolvedValue({
    registrations: [registration()],
    flagged_count: 0,
  });
  vi.mocked(addGstRegistration).mockResolvedValue(registration());
  vi.mocked(deactivateGstRegistration).mockResolvedValue(
    registration({ active: false, deactivated_at: '2026-04-01T00:00:00Z' }),
  );
  vi.mocked(flagGstRegistration).mockResolvedValue(
    registration({ flag_status: 'FLAGGED', flag_reason: 'Returns unfiled' }),
  );
  vi.mocked(unflagGstRegistration).mockResolvedValue(registration());
});

describe('GstRegistrationsSection', () => {
  it('names the branch by its state, which is what identifies it to a person', async () => {
    renderSection();
    expect(await screen.findByText('Maharashtra')).toBeInTheDocument();
    // "Not verified", never "Active": nobody has checked it against the portal, and
    // saying otherwise would be a claim the CRM has no basis for.
    expect(screen.getByText(/Not verified/)).toBeInTheDocument();
  });

  it('says so when a state code is not one we know, rather than showing nothing', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [registration({ state_code: '77', state_name: null })],
      flagged_count: 0,
    });
    renderSection();
    expect(await screen.findByText(/State code 77/)).toBeInTheDocument();
  });

  it('does not ask for the state when adding, because the GSTIN carries it', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /Add registration/ }));

    expect(screen.getByText(/state comes from the GSTIN/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/state/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('e.g. 27ABCDE1234F1Z5'), {
      target: { value: '29ABCDE1234F1Z5' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Add' }));

    await waitFor(() => expect(vi.mocked(addGstRegistration)).toHaveBeenCalled());
    expect(vi.mocked(addGstRegistration).mock.calls[0][1]).toMatchObject({
      gstin: '29ABCDE1234F1Z5',
    });
  });

  it('shows a deactivated branch rather than hiding it', async () => {
    // It is how a deal handed over through it is explained; hiding it would make that
    // deal's invoicing branch look as though it came from nowhere.
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [registration({ active: false, deactivated_at: '2026-04-01T00:00:00Z' })],
      flagged_count: 0,
    });
    renderSection();
    expect(await screen.findByText(/Deactivated/)).toBeInTheDocument();
    expect(screen.getByText('Maharashtra')).toBeInTheDocument();
    // And offers no actions on it: there is nothing to flag or deactivate.
    expect(screen.queryByRole('button', { name: 'Deactivate' })).not.toBeInTheDocument();
  });

  it('counts the flagged branches and says what it means', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [registration({ flag_status: 'FLAGGED', flag_reason: 'Returns unfiled' })],
      flagged_count: 1,
    });
    renderSection();
    expect(await screen.findByRole('alert')).toHaveTextContent('1 branch flagged');
    expect(screen.getByText(/cannot be handed over/)).toBeInTheDocument();
    // The reason is shown, because it is what somebody hitting the block must act on.
    expect(screen.getByText(/Returns unfiled/)).toBeInTheDocument();
  });

  it('requires a reason to flag, and says what the reason is for', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /Flag/ }));

    expect(screen.getByText(/what a blocked handover will say/)).toBeInTheDocument();
    // Nothing to submit until there is a reason.
    expect(screen.getByRole('button', { name: 'Flag branch' })).toBeDisabled();

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Returns unfiled' } });
    fireEvent.click(screen.getByRole('button', { name: 'Flag branch' }));

    await waitFor(() => expect(vi.mocked(flagGstRegistration)).toHaveBeenCalled());
    expect(vi.mocked(flagGstRegistration).mock.calls[0][1]).toEqual({
      reason: 'Returns unfiled',
    });
  });

  it('requires a reason to lift a flag too', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [registration({ flag_status: 'FLAGGED', flag_reason: 'Returns unfiled' })],
      flagged_count: 1,
    });
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /Lift flag/ }));

    expect(screen.getByText(/stops being readable on the row/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'Now filed' } });
    fireEvent.click(screen.getByRole('button', { name: 'Lift flag' }));

    await waitFor(() => expect(vi.mocked(unflagGstRegistration)).toHaveBeenCalled());
  });

  it('offers no flag control to a role that may not flag', async () => {
    // A flag stops trade through the branch, so it is COMPLIANCE's decision. The
    // server refuses OPERATIONS; the screen does not offer it either, rather than
    // showing a button that 403s.
    renderSection({ canEdit: true, canFlag: false });
    await screen.findByText('Maharashtra');
    expect(screen.queryByRole('button', { name: /Flag/ })).not.toBeInTheDocument();
    // But recording and deactivating a branch stay available.
    expect(screen.getByRole('button', { name: 'Deactivate' })).toBeInTheDocument();
  });

  it('shows the portal link only when the server sent one', async () => {
    renderSection();
    await screen.findByText('Maharashtra');
    // No `verify_url`: this viewer sees the GSTIN masked, and the link would carry it.
    expect(screen.queryByRole('link', { name: /GST portal/ })).not.toBeInTheDocument();

    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [
        registration({
          verify_url: 'https://services.gst.gov.in/services/searchtp?tin=27ABCDE1234F1Z5',
        }),
      ],
      flagged_count: 0,
    });
    renderSection();
    const [link] = await screen.findAllByRole('link', { name: /GST portal/ });
    expect(link).toHaveAttribute(
      'href',
      'https://services.gst.gov.in/services/searchtp?tin=27ABCDE1234F1Z5',
    );
  });

  it('warns that a shared GSTIN is not flagged on the other company', async () => {
    // Decision IQ-9 keeps duplicates warn-only, so the flag belongs to one row.
    // Somebody who did not know that would believe they had stopped trade that is
    // still running on the other company.
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [
        registration({
          flag_status: 'FLAGGED',
          flag_reason: 'Returns unfiled',
          also_held_by: [OTHER],
        }),
      ],
      flagged_count: 1,
    });
    renderSection();
    expect(await screen.findByText(/does not flag theirs/)).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /another company/ })).toHaveAttribute(
      'href',
      `/companies/${OTHER}`,
    );
  });

  it('says there is nothing yet, and what that prevents', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [],
      flagged_count: 0,
    });
    renderSection();
    expect(await screen.findByText(/No GST registrations recorded/)).toBeInTheDocument();
    expect(screen.getByText(/cannot name an invoicing branch/)).toBeInTheDocument();
  });
});
