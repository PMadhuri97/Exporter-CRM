import { fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getBankActivity,
  getScreeningReview,
  listCompanyDocuments,
  listVerificationResults,
} from '../api';

import {
  bankActivity,
  COMPANY_ID,
  renderWithClient,
  resultList,
  screeningList,
  verificationResult,
} from './verification-test-fixtures';
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
