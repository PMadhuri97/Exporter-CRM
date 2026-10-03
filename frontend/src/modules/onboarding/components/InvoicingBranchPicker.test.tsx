import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { toast } from 'sonner';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { listGstRegistrations, setDealInvoicingBranch } from '../api';
import type { Deal, GstRegistration } from '../types';

import { InvoicingBranchPicker } from './InvoicingBranchPicker';

vi.mock('../api', () => ({
  listGstRegistrations: vi.fn(),
  setDealInvoicingBranch: vi.fn(),
}));
vi.mock('sonner', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const DEAL = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const SELLER = 'ssssssss-ssss-4sss-8sss-ssssssssssss';
const MAHARASHTRA = 'mmmmmmmm-mmmm-4mmm-8mmm-mmmmmmmmmmmm';
const KARNATAKA = 'kkkkkkkk-kkkk-4kkk-8kkk-kkkkkkkkkkkk';
const GUJARAT = 'gggggggg-gggg-4ggg-8ggg-gggggggggggg';

/** As OPERATIONS receives it: the server masks all but the last four characters. */
function registration(overrides: Partial<GstRegistration> = {}): GstRegistration {
  return {
    id: MAHARASHTRA,
    customer_id: SELLER,
    gstin: '•••••••••••F1Z5',
    state_code: '27',
    state_name: 'Maharashtra',
    status: 'ACTIVE',
    address: null,
    flag_status: 'NONE',
    flag_reason: null,
    active: true,
    deactivated_at: null,
    created_at: '2026-03-01T00:00:00Z',
    verify_url: null,
    also_held_by: [],
    ...overrides,
  };
}

const BRANCHES = [
  registration(),
  registration({
    id: KARNATAKA,
    gstin: '•••••••••••G1Z3',
    state_code: '29',
    state_name: 'Karnataka',
  }),
  registration({
    id: GUJARAT,
    gstin: '•••••••••••H1Z1',
    state_code: '24',
    state_name: 'Gujarat',
    active: false,
    deactivated_at: '2026-04-01T00:00:00Z',
  }),
];

function renderPicker({
  recordedId = null as string | null,
  canEdit = true,
  closed = false,
} = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <InvoicingBranchPicker
        dealId={DEAL}
        sellerId={SELLER}
        recordedId={recordedId}
        canEdit={canEdit}
        closed={closed}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listGstRegistrations).mockResolvedValue({
    registrations: BRANCHES,
    flagged_count: 0,
  });
  vi.mocked(setDealInvoicingBranch).mockResolvedValue({} as Deal);
});

describe('InvoicingBranchPicker — choosing', () => {
  it("offers the seller's active branches by state and GSTIN as served, and no other", async () => {
    renderPicker();
    const select = await screen.findByLabelText('Invoiced from');

    expect(listGstRegistrations).toHaveBeenCalledWith(SELLER);
    const options = within(select)
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(options).toEqual([
      'Choose a branch…',
      'Maharashtra · •••••••••••F1Z5',
      'Karnataka · •••••••••••G1Z3',
    ]);
    // A deactivated branch is on record, but nothing new is invoiced from it.
    expect(screen.queryByText(/Gujarat/)).not.toBeInTheDocument();
  });

  it('records the chosen branch by its id, through PUT /deals/{id}/invoicing-branch', async () => {
    renderPicker();
    fireEvent.change(await screen.findByLabelText('Invoiced from'), {
      target: { value: KARNATAKA },
    });

    await waitFor(() =>
      expect(setDealInvoicingBranch).toHaveBeenCalledWith(DEAL, {
        gst_registration_id: KARNATAKA,
      }),
    );
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith('Invoiced from Karnataka'));
  });

  it('changes a recorded branch, and clears it with null', async () => {
    renderPicker({ recordedId: MAHARASHTRA });
    const select = await screen.findByLabelText('Invoiced from');
    expect(select).toHaveValue(MAHARASHTRA);
    // Nothing to "choose" once one is recorded.
    expect(within(select).queryByText('Choose a branch…')).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'Clear' }));
    await waitFor(() =>
      expect(setDealInvoicingBranch).toHaveBeenCalledWith(DEAL, { gst_registration_id: null }),
    );
  });

  it('offers no Clear while nothing is recorded', async () => {
    renderPicker();
    await screen.findByLabelText('Invoiced from');
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
  });

  it("shows the server's refusal in its own words", async () => {
    vi.mocked(setDealInvoicingBranch).mockRejectedValue(
      new Error('GST registration is deactivated'),
    );
    renderPicker();
    fireEvent.change(await screen.findByLabelText('Invoiced from'), {
      target: { value: MAHARASHTRA },
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('GST registration is deactivated'),
    );
  });
});

describe('InvoicingBranchPicker — what the handover guard will say', () => {
  it('says a handover needs it while the seller has an active branch and none is recorded', async () => {
    renderPicker();
    expect(await screen.findByRole('status')).toHaveTextContent(
      /Not recorded.*handover asks which one this deal is invoiced from/,
    );
  });

  it('says nothing is needed when the seller has no active GST registration', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [BRANCHES[2]!],
      flagged_count: 0,
    });
    renderPicker();

    expect(
      await screen.findByText(/no active GST registration, so a handover does not ask for one/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText('Invoiced from')).not.toBeInTheDocument();
  });

  it('warns that a flagged branch blocks the handover', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [registration({ flag_status: 'FLAGGED', flag_reason: 'Returns unfiled' })],
      flagged_count: 1,
    });
    renderPicker({ recordedId: MAHARASHTRA });

    expect(await screen.findByRole('status')).toHaveTextContent(
      /This branch is flagged.*cannot be handed over/,
    );
    // The option says so before it is chosen, too.
    expect(screen.getByRole('option', { name: /Maharashtra.*flagged/ })).toBeInTheDocument();
  });

  it('keeps a recorded branch that was deactivated since, without offering it again', async () => {
    renderPicker({ recordedId: GUJARAT });
    const select = await screen.findByLabelText('Invoiced from');

    expect(select).toHaveValue(GUJARAT);
    expect(
      within(select).getByRole('option', { name: /Gujarat.*deactivated/ }),
    ).toBeDisabled();
  });
});

describe('InvoicingBranchPicker — when it is read-only', () => {
  it('shows a closed deal its recorded branch, frozen, with nothing to change', async () => {
    renderPicker({ recordedId: KARNATAKA, closed: true });

    expect(await screen.findByText('Karnataka')).toBeInTheDocument();
    expect(screen.getByText('•••••••••••G1Z3')).toBeInTheDocument();
    expect(screen.getByText(/Frozen with the deal/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Invoiced from')).toBeNull();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
    // Nothing a closed deal can act on.
    expect(screen.queryByRole('status')).not.toBeInTheDocument();
  });

  it('says so when a closed deal recorded none', async () => {
    renderPicker({ closed: true });
    expect(await screen.findByText('No invoicing branch was recorded.')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('gives a role that may not record one the value, and no control', async () => {
    renderPicker({ recordedId: MAHARASHTRA, canEdit: false });

    expect(await screen.findByText('Maharashtra')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
    expect(setDealInvoicingBranch).not.toHaveBeenCalled();
  });

  it('marks a recorded branch that is flagged or deactivated', async () => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [registration({ flag_status: 'FLAGGED', active: false })],
      flagged_count: 1,
    });
    renderPicker({ recordedId: MAHARASHTRA, closed: true });

    expect(await screen.findByText('Flagged')).toBeInTheDocument();
    expect(screen.getByText('Deactivated')).toBeInTheDocument();
  });
});
