import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  approveBankAccount,
  listBankAccounts,
  listCompanyDocuments,
  listVerificationResults,
  proposeBankAccount,
  revealBankAccount,
  verifyBankAccount,
} from '../api';
import type { BankAccount } from '../types';

import { BankAccountsSection } from './BankAccountsSection';

vi.mock('../api', () => ({
  listBankAccounts: vi.fn(),
  proposeBankAccount: vi.fn(),
  approveBankAccount: vi.fn(),
  rejectBankAccount: vi.fn(),
  verifyBankAccount: vi.fn(),
  setPrimaryBankAccount: vi.fn(),
  deactivateBankAccount: vi.fn(),
  revealBankAccount: vi.fn(),
  listCompanyDocuments: vi.fn(),
  listVerificationResults: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const COMPANY = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function account(overrides: Partial<BankAccount> = {}): BankAccount {
  return {
    id: 'b1',
    customer_id: COMPANY,
    account_holder_name: 'Acme Exports Pvt Ltd',
    bank_name: 'HDFC Bank',
    branch: null,
    ifsc: 'HDFC0000060',
    swift_bic: null,
    currency: 'USD',
    account_type: 'EEFC',
    ad_code: null,
    is_primary: false,
    status: 'PENDING_APPROVAL',
    replaces_id: null,
    proposed_by: 'u1',
    proposed_by_name: 'Ravi RM',
    proposal_reason: null,
    approved_by: null,
    approved_by_name: null,
    approved_at: null,
    rejected_by: null,
    rejected_at: null,
    rejection_reason: null,
    verification_method: null,
    evidence_document_id: null,
    verification_result_id: null,
    verified_by: null,
    verified_by_name: null,
    verified_at: null,
    deactivated_at: null,
    deactivation_reason: null,
    created_at: '2026-10-01T00:00:00Z',
    can_approve: false,
    account_number_masked: '••••5678',
    iban_masked: null,
    ...overrides,
  };
}

function list(
  accounts: BankAccount[],
  capabilities = { can_propose: true, can_approve: false, can_reveal: false },
) {
  vi.mocked(listBankAccounts).mockResolvedValue({ accounts, capabilities });
}

function renderSection() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <BankAccountsSection customerId={COMPANY} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCompanyDocuments).mockResolvedValue({
    documents: [{ id: 'd1', file_name: 'cheque.pdf', scan_status: 'AVAILABLE' }],
    total: 1,
  } as never);
  vi.mocked(listVerificationResults).mockResolvedValue({ results: [], total: 0 } as never);
});

describe('BankAccountsSection', () => {
  it('shows the number masked with the status, and no reveal for a reader who may not', async () => {
    list([account()]);
    renderSection();

    expect(await screen.findByTestId('bank-number')).toHaveTextContent('••••5678');
    expect(screen.getByText('Pending approval')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Reveal/ })).not.toBeInTheDocument();
    // The proposer is not offered Approve: the server said so.
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('reveals the full number on request, for a reader who may', async () => {
    list([account({ status: 'VERIFIED' })], { can_propose: true, can_approve: true, can_reveal: true });
    vi.mocked(revealBankAccount).mockResolvedValue({ id: 'b1', account_number: '50200012345678', iban: null });
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: /Reveal/ }));

    await waitFor(() => expect(screen.getByTestId('bank-number')).toHaveTextContent('50200012345678'));
  });

  it('offers Approve where the server allows it', async () => {
    list([account({ can_approve: true })]);
    vi.mocked(approveBankAccount).mockResolvedValue(account({ status: 'PENDING_VERIFICATION' }));
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));

    await waitFor(() => expect(approveBankAccount).toHaveBeenCalledWith('b1'));
  });

  it('proposes an account with its details', async () => {
    list([]);
    vi.mocked(proposeBankAccount).mockResolvedValue(account());
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /Propose account/ }));

    fireEvent.change(screen.getByLabelText(/^Account holder name/), { target: { value: 'Acme' } });
    fireEvent.change(screen.getByLabelText(/^Bank/), { target: { value: 'HDFC Bank' } });
    fireEvent.change(screen.getByLabelText(/^Account number/), { target: { value: '50200012345678' } });
    fireEvent.change(screen.getByLabelText(/^IFSC/), { target: { value: 'HDFC0000060' } });
    fireEvent.change(screen.getByLabelText(/^Currency/), { target: { value: 'usd' } });
    fireEvent.change(screen.getByLabelText(/^Account type/), { target: { value: 'EEFC' } });
    fireEvent.click(screen.getByRole('button', { name: 'Propose for approval' }));

    await waitFor(() =>
      expect(proposeBankAccount).toHaveBeenCalledWith(
        COMPANY,
        expect.objectContaining({
          account_number: '50200012345678',
          currency: 'USD',
          account_type: 'EEFC',
          replaces_id: null,
        }),
      ),
    );
  });

  it('verifies an approved account with a document on the record', async () => {
    list([account({ status: 'PENDING_VERIFICATION' })], { can_propose: true, can_approve: true, can_reveal: true });
    vi.mocked(verifyBankAccount).mockResolvedValue(account({ status: 'VERIFIED' }));
    renderSection();

    fireEvent.click(await screen.findByRole('button', { name: 'Verify' }));
    const form = screen.getByRole('button', { name: 'Verify' }).closest('form')!;
    await within(form).findByRole('option', { name: 'cheque.pdf' });
    fireEvent.change(within(form).getByLabelText(/^Document/), { target: { value: 'd1' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Verify' }));

    await waitFor(() =>
      expect(verifyBankAccount).toHaveBeenCalledWith('b1', {
        method: 'CANCELLED_CHEQUE',
        evidence_document_id: 'd1',
      }),
    );
  });

  it('offers a change on a verified account and keeps past versions behind "Show history"', async () => {
    list([
      account({ status: 'VERIFIED', is_primary: true }),
      account({ id: 'b0', status: 'INACTIVE', account_number_masked: '••••1111' }),
    ]);
    renderSection();

    expect(await screen.findByRole('button', { name: 'Propose change' })).toBeInTheDocument();
    expect(screen.getAllByTestId('bank-account-row')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Show history (1)' }));
    expect(screen.getAllByTestId('bank-account-row')).toHaveLength(2);
  });
});
