import { QueryClient } from '@tanstack/react-query';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getBankActivity,
  getScreeningReview,
  listCompanyDocuments,
  listVerificationResults,
  reviewVerification,
  updateScreeningReviewItem,
} from '../api';

import {
  bankActivity,
  CATALOGUE,
  COMPANY_ID,
  renderWithClient,
  resultList,
  screeningItem,
  screeningList,
  verificationResult,
} from '../testing/verification-fixtures';
import { VerificationSection } from './VerificationSection';

vi.mock('../api', () => ({
  getBankActivity: vi.fn(),
  getScreeningItemHistory: vi.fn(),
  getScreeningReview: vi.fn(),
  listCompanyDocuments: vi.fn(),
  listVerificationResults: vi.fn(),
  reviewVerification: vi.fn(),
  triggerVerification: vi.fn(),
  updateScreeningReviewItem: vi.fn(),
}));

// No auth provider and no current-user mock anywhere in this file: the workspace
// decides nothing from a role. Every "may I" comes from the served capabilities.
function renderSection() {
  return renderWithClient(<VerificationSection customerId={COMPANY_ID} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listVerificationResults).mockResolvedValue(resultList([verificationResult()]));
  vi.mocked(getScreeningReview).mockResolvedValue(screeningList());
  vi.mocked(getBankActivity).mockResolvedValue(bankActivity());
  vi.mocked(listCompanyDocuments).mockResolvedValue({
    documents: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
});

describe('VerificationSection — states', () => {
  it('reads the company’s results as an EXPORTER subject', async () => {
    renderSection();
    await screen.findByTestId('verification-result');
    expect(listVerificationResults).toHaveBeenCalledWith('EXPORTER', COMPANY_ID);
  });

  it('shows a loading state first', () => {
    vi.mocked(listVerificationResults).mockReturnValue(new Promise(() => {}));
    renderSection();
    expect(screen.getByTestId('verification-loading')).toBeInTheDocument();
  });

  it('says so when no result has been recorded', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(resultList([]));
    renderSection();
    expect(await screen.findByText('No screening results yet')).toBeInTheDocument();
    // What is missing is listed rather than silently absent.
    expect(screen.getByText('10 check types have no result')).toBeInTheDocument();
  });

  it('says so when the results cannot be loaded', async () => {
    vi.mocked(listVerificationResults).mockRejectedValue(new Error('boom'));
    renderSection();
    expect(await screen.findByText(/Could not load screening results/)).toBeInTheDocument();
  });

  it('keeps the checklist beside the results', async () => {
    renderSection();
    expect(await screen.findByTestId('screening-checklist')).toBeInTheDocument();
    expect((await screen.findAllByTestId('screening-item')).length).toBe(8);
  });
});

describe('VerificationSection — capabilities, not roles', () => {
  it('offers recording and reviewing when the server says the caller may', async () => {
    renderSection();
    await screen.findByTestId('verification-result');
    expect(screen.getByRole('button', { name: 'Record a result' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
  });

  it('offers neither when the server says the caller may not', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      resultList([verificationResult()], { can_record_result: false, can_review: false }),
    );
    renderSection();
    await screen.findByTestId('verification-result');
    expect(screen.queryByRole('button', { name: 'Record a result' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
  });

  it('opens the manual result form on the company, with the company’s documents', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a result' }));
    const form = screen.getByTestId('manual-result-form');
    expect(within(form).getByText('Evidence documents from this company')).toBeInTheDocument();
    expect(await within(form).findByText('No scanned-clean documents to attach.')).toBeInTheDocument();
    expect(listCompanyDocuments).toHaveBeenCalledWith(COMPANY_ID, {});
    fireEvent.click(within(form).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByTestId('manual-result-form')).not.toBeInTheDocument();
  });
});

describe('VerificationSection — every result on the company is shown', () => {
  it('lists a result outside the screening set, reviewable, instead of dropping it', async () => {
    // A BANK_ACCOUNT result in REVIEW blocks CLEAR like any other company result.
    vi.mocked(listVerificationResults).mockResolvedValue(
      resultList([
        verificationResult(),
        verificationResult({
          id: 'aaaaaaaa-0000-4000-8000-000000000002',
          verification_type: 'BANK_ACCOUNT',
        }),
      ]),
    );
    renderSection();
    const other = await screen.findByTestId('other-company-checks');
    expect(within(other).getByText('Bank Account')).toBeInTheDocument();
    expect(within(other).getByRole('button', { name: 'Review' })).toBeInTheDocument();
    expect(screen.getAllByTestId('verification-result')).toHaveLength(2);
    expect(screen.getByRole('button', { name: /Company screenings/ })).toHaveTextContent('(2)');
  });

  it('shows no such group when every result is in the screening set', async () => {
    renderSection();
    await screen.findByTestId('verification-result');
    expect(screen.queryByTestId('other-company-checks')).not.toBeInTheDocument();
  });
});

describe('VerificationSection — writes refresh the background check', () => {
  // Developer 4A's panel disables CLEAR from ['backgroundCheck', id]; a write here that
  // did not refresh it left CLEAR disabled after the inputs were complete.
  function invalidatedKeys(spy: { mock: { calls: unknown[][] } }) {
    return spy.mock.calls.map((call) => (call[0] as { queryKey: unknown[] }).queryKey);
  }

  it('after a review', async () => {
    const spy = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    try {
      vi.mocked(reviewVerification).mockResolvedValue(verificationResult());
      renderSection();
      fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
      fireEvent.change(screen.getByLabelText('Verdict'), { target: { value: 'ACCEPTED' } });
      fireEvent.click(screen.getByRole('button', { name: 'Record review' }));

      await waitFor(() =>
        expect(invalidatedKeys(spy)).toContainEqual(['backgroundCheck', COMPANY_ID]),
      );
      expect(invalidatedKeys(spy)).toContainEqual(['companyHistory', COMPANY_ID]);
    } finally {
      spy.mockRestore();
    }
  });

  it('after a screening decision', async () => {
    const spy = vi.spyOn(QueryClient.prototype, 'invalidateQueries');
    try {
      vi.mocked(updateScreeningReviewItem).mockResolvedValue(screeningItem());
      renderSection();
      const select = await screen.findByLabelText(`${CATALOGUE[0]!.label} status`);
      fireEvent.change(select, { target: { value: 'PASSED' } });
      const card = select.closest('[data-testid="screening-item"]') as HTMLElement;
      fireEvent.click(within(card).getByRole('button', { name: 'Save' }));

      await waitFor(() =>
        expect(invalidatedKeys(spy)).toContainEqual(['backgroundCheck', COMPANY_ID]),
      );
      expect(invalidatedKeys(spy)).toContainEqual(['companyHistory', COMPANY_ID]);
    } finally {
      spy.mockRestore();
    }
  });
});

describe('VerificationSection — bank activity', () => {
  it('says the bank feed is not connected, with no zero counts', async () => {
    renderSection();
    await screen.findByTestId('verification-result');
    fireEvent.click(screen.getByRole('button', { name: /Bank activity/ }));
    expect(await screen.findByTestId('bank-feed-status')).toHaveTextContent('Not connected');
    expect(screen.queryByText('Connected accounts')).not.toBeInTheDocument();
    // Recording a result belongs to the company tab.
    expect(screen.queryByRole('button', { name: 'Record a result' })).not.toBeInTheDocument();
  });
});
