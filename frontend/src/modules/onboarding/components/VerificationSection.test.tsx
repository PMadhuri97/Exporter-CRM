import { QueryClient } from '@tanstack/react-query';
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getBackgroundCheck,
  getBankActivity,
  listCheckCycles,
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
  getBackgroundCheck: vi.fn(),
  listCheckCycles: vi.fn(),
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
    expect((await screen.findAllByTestId('screening-item')).length).toBe(CATALOGUE.length);
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
  // The background-check panel disables CLEAR from ['backgroundCheck', id]; a write here that
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

describe('VerificationSection — filters', () => {
  const manualPassed = verificationResult({ id: 'r-manual', status: 'PASSED', provenance: 'MANUAL' });
  const manualFailed = verificationResult({ id: 'r-failed', verification_type: 'SANCTIONS', status: 'FAILED' });
  const highRisk = verificationResult({ id: 'r-high', verification_type: 'AML', status: 'PASSED', risk_level: 'HIGH' });
  const stub = verificationResult({ id: 'r-stub', verification_type: 'GST', provider: 'rxil_stub', provenance: 'STUB', status: 'PASSED' });

  beforeEach(() => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      resultList([manualPassed, manualFailed, highRisk, stub]),
    );
  });

  it('offers All, Automated, Manual and Flagged with their counts', async () => {
    renderSection();
    const group = await screen.findByRole('group', { name: 'Filter checks' });
    expect(within(group).getAllByRole('button').map((button) => button.textContent)).toEqual([
      'All (4)',
      'Automated (0)',
      'Manual (3)',
      'Flagged (2)',
    ]);
    expect(screen.getAllByTestId('verification-result')).toHaveLength(4);
  });

  it('Flagged shows FAILED and HIGH/CRITICAL results only', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /^Flagged/ }));
    expect(screen.getAllByTestId('verification-result')).toHaveLength(2);
  });

  it('Automated excludes the RXIL stub and says honestly that no provider is connected', async () => {
    renderSection();
    fireEvent.click(await screen.findByRole('button', { name: /^Automated/ }));
    expect(screen.queryAllByTestId('verification-result')).toHaveLength(0);
    expect(screen.getByTestId('verification-filter-empty')).toHaveTextContent(
      'No provider integration is connected',
    );
  });
});

describe('VerificationSection — check cycles', () => {
  it('lists the current cycle’s results and keeps an earlier cycle’s readable, not reviewable', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue({
      company_id: COMPANY_ID,
      value: 'IN_REVIEW',
      risk_rating: null,
      latest_decision_id: null,
      clearing_decision_id: null,
      decided_at: null,
      allowed_moves: [],
      clear_blocked_reasons: [],
      compliance: { is_clear: false, clear_expires_at: null, is_clear_current: false, sanctions: 'MISSING', aml: 'MISSING' },
      awaiting_approval: false,
      rekyc_due: false,
      current_cycle: {
        id: 'cycle-2', company_id: COMPANY_ID, number: 2, kind: 'RE_KYC', reason: 'Annual',
        started_at: '2026-10-01T09:00:00Z', started_by: 'x', started_by_name: null,
        source: 's', rules_version: null, is_current: true,
      },
      allowed_cycle_actions: [],
    });
    vi.mocked(listCheckCycles).mockResolvedValue({
      cycles: [
        {
          id: 'cycle-1', company_id: COMPANY_ID, number: 1, kind: 'INITIAL', reason: null,
          started_at: '2026-09-01T09:00:00Z', started_by: 'x', started_by_name: null,
          source: 'MIGRATION', rules_version: null, is_current: false,
        },
      ],
      current_cycle_id: 'cycle-2',
    });
    vi.mocked(listVerificationResults).mockResolvedValue(
      resultList([
        verificationResult({ id: 'now', cycle_id: 'cycle-2' }),
        verificationResult({ id: 'old', cycle_id: 'cycle-1', status: 'REVIEW' }),
      ]),
    );
    renderSection();
    const earlier = await screen.findByTestId('earlier-cycle-results');
    expect(earlier).toHaveTextContent('Cycle 1 · Initial check — 1 result, read-only');
    // The current cycle's result is listed and reviewable; the earlier one is folded away.
    expect(screen.getAllByTestId('verification-result')).toHaveLength(1);
    fireEvent.click(within(earlier).getByRole('button', { expanded: false }));
    expect(within(earlier).getAllByTestId('verification-result')).toHaveLength(1);
    expect(within(earlier).queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
  });
});

describe('VerificationSection — company-keyed checks', () => {
  it('lists a deal-buyer check mapped to this company, saying where it was recorded', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      resultList([
        verificationResult(),
        verificationResult({
          id: 'aaaaaaaa-0000-4000-8000-000000000002',
          verification_type: 'SANCTIONS',
          entity_type: 'BUYER',
          entity_reference: '44444444-4444-4444-8444-444444444444',
          subject_company_id: COMPANY_ID,
          subject_snapshot: {
            deal_buyer_id: '44444444-4444-4444-8444-444444444444',
            deal_id: '55555555-5555-4555-8555-555555555555',
            name: 'Rotterdam Trading BV',
            country: 'NL',
            registration_number: null,
            tax_id: null,
          },
        }),
      ]),
    );
    renderSection();

    const label = await screen.findByTestId('recorded-as-buyer-check');
    expect(label).toHaveTextContent("Recorded on a deal as the buyer's check (Rotterdam Trading BV)");
    // The company's own check carries no such label.
    expect(screen.getAllByTestId('recorded-as-buyer-check')).toHaveLength(1);
  });
});
