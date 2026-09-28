import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import {
  listDealDocuments,
  listVerificationResults,
  reviewVerification,
  triggerVerification,
} from '../api';
import type {
  CrmDocument,
  VerificationResult,
  VerificationResultList,
  VerificationReview,
} from '../types';

import { BuyerChecks } from './BuyerChecks';

vi.mock('../api', () => ({
  listDealDocuments: vi.fn(),
  listVerificationResults: vi.fn(),
  reviewVerification: vi.fn(),
  triggerVerification: vi.fn(),
}));

const DEAL_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const BUYER_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const RESULT_ID = 'aaaaaaaa-0000-4000-8000-000000000001';

function review(overrides: Partial<VerificationReview> = {}): VerificationReview {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    verification_result_id: RESULT_ID,
    review_status: 'ACCEPTED',
    reviewed_by: '22222222-2222-4222-8222-222222222222',
    reviewed_at: '2026-09-28T10:00:00Z',
    note: null,
    supersedes_review_id: null,
    ...overrides,
  };
}

function check(overrides: Partial<VerificationResult> = {}): VerificationResult {
  return {
    id: RESULT_ID,
    verification_type: 'SANCTIONS',
    entity_type: 'BUYER',
    entity_reference: BUYER_ID,
    provider: 'manual',
    provenance: 'MANUAL',
    is_placeholder: false,
    provider_reference: null,
    status: 'PASSED',
    risk_level: null,
    performed_at: '2026-09-28T09:00:00Z',
    valid_until: null,
    normalized_result: {},
    evidence_reference: null,
    evidence_note: 'Screened against the consolidated list.',
    evidence_refs: [],
    subject_snapshot: {
      deal_buyer_id: BUYER_ID,
      deal_id: DEAL_ID,
      name: 'Rotterdam Trading BV',
      country: 'NL',
      registration_number: 'KVK-12345678',
      tax_id: 'NL123456789B01',
    },
    reviewed_by: null,
    review_status: null,
    latest_review_id: null,
    latest_reviewed_at: null,
    reviews: [],
    created_at: '2026-09-28T09:00:00Z',
    updated_at: '2026-09-28T09:00:00Z',
    ...overrides,
  };
}

function list(
  results: VerificationResult[],
  capabilities = { can_record_result: true, can_review: true },
): VerificationResultList {
  return {
    entity_type: 'BUYER',
    entity_reference: BUYER_ID,
    results,
    total: results.length,
    capabilities,
  };
}

function document(overrides: Partial<CrmDocument> = {}): CrmDocument {
  return {
    id: '33333333-3333-4333-8333-333333333333',
    company_id: null,
    deal_id: DEAL_ID,
    category: 'BUYER',
    document_type: 'buyer_registry_extract',
    source: 'INTERNAL',
    file_name: 'registry-extract.pdf',
    content_type: 'application/pdf',
    size_bytes: 1024,
    uploaded_by: null,
    uploaded_at: '2026-09-27T09:00:00Z',
    scan_status: 'AVAILABLE',
    scanner_name: 'pass-through',
    is_downloadable: true,
    ...overrides,
  };
}

function renderChecks() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BuyerChecks dealId={DEAL_ID} dealBuyerId={BUYER_ID} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listVerificationResults).mockResolvedValue(list([check()]));
  vi.mocked(listDealDocuments).mockResolvedValue({
    documents: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
});

describe('BuyerChecks — reading', () => {
  it('reads the checks by the buyer id, never the company or the deal', async () => {
    renderChecks();
    await screen.findByTestId('buyer-check');
    expect(listVerificationResults).toHaveBeenCalledWith('BUYER', BUYER_ID);
  });

  it('shows a loading state first', () => {
    vi.mocked(listVerificationResults).mockReturnValue(new Promise(() => {}));
    renderChecks();
    expect(screen.getByText('Loading buyer checks…')).toBeInTheDocument();
  });

  it('says so when the checks cannot be loaded', async () => {
    vi.mocked(listVerificationResults).mockRejectedValue(new Error('boom'));
    renderChecks();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Buyer checks could not be loaded.',
    );
  });

  it('says so when no check has been recorded', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(list([]));
    renderChecks();
    expect(
      await screen.findByText('No checks have been recorded on this buyer yet.'),
    ).toBeInTheDocument();
  });

  it('shows each check with its status, provenance, snapshot and evidence', async () => {
    renderChecks();
    const row = await screen.findByTestId('buyer-check');
    expect(within(row).getByText('Sanctions')).toBeInTheDocument();
    expect(within(row).getByText('Passed')).toBeInTheDocument();
    expect(within(row).getByText(/Manual \(person\)/)).toBeInTheDocument();
    expect(within(row).getByText('Screened against the consolidated list.')).toBeInTheDocument();

    const snapshot = within(row).getByTestId('buyer-snapshot');
    expect(snapshot).toHaveTextContent('Rotterdam Trading BV');
    expect(snapshot).toHaveTextContent('NL');
    expect(snapshot).toHaveTextContent('KVK-12345678');
    expect(snapshot).toHaveTextContent('NL123456789B01');
  });

  it('shows the snapshot exactly as the server masked it', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      list([
        check({
          subject_snapshot: {
            deal_buyer_id: BUYER_ID,
            deal_id: DEAL_ID,
            name: 'Rotterdam Trading BV',
            country: 'NL',
            registration_number: '••••••••5678',
            tax_id: '••••••••••B01',
          },
        }),
      ]),
    );
    renderChecks();
    const snapshot = await screen.findByTestId('buyer-snapshot');
    expect(snapshot).toHaveTextContent('••••••••5678');
    expect(snapshot).toHaveTextContent('••••••••••B01');
    expect(snapshot).not.toHaveTextContent('KVK-12345678');
  });

  it('labels a stub result and a placeholder honestly', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      list([
        check({ id: 'stub', provider: 'rxil_stub', provenance: 'STUB' }),
        check({ id: 'placeholder', status: 'PENDING', is_placeholder: true }),
      ]),
    );
    renderChecks();
    const [stub, placeholder] = await screen.findAllByTestId('buyer-check');
    expect(stub).toHaveTextContent('RXIL stub, not RXIL');
    expect(placeholder).toHaveTextContent('Placeholder · no provider ran this check');
  });

  it('shows the whole review chain, first to current', async () => {
    const first = review();
    const second = review({
      id: '44444444-4444-4444-8444-444444444444',
      review_status: 'REJECTED',
      note: 'Registry mismatch',
      supersedes_review_id: first.id,
      reviewed_at: '2026-09-28T11:00:00Z',
    });
    vi.mocked(listVerificationResults).mockResolvedValue(
      list([
        check({
          review_status: 'REJECTED',
          latest_review_id: second.id,
          reviews: [first, second],
        }),
      ]),
    );
    renderChecks();
    const entries = await screen.findAllByTestId('review-chain-entry');
    expect(entries).toHaveLength(2);
    expect(entries[0]).toHaveTextContent('Accepted');
    expect(entries[0]).toHaveTextContent('Superseded');
    expect(entries[1]).toHaveTextContent('Rejected');
    expect(entries[1]).toHaveTextContent('Current');
    expect(entries[1]).toHaveTextContent('Registry mismatch');
  });
});

describe('BuyerChecks — actions follow the served capabilities', () => {
  it('offers no record or review action when the server says the caller may not', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      list([check()], { can_record_result: false, can_review: false }),
    );
    renderChecks();
    await screen.findByTestId('buyer-check');
    expect(screen.queryByRole('button', { name: 'Record a check' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
  });

  it('offers both when the server says the caller may', async () => {
    renderChecks();
    await screen.findByTestId('buyer-check');
    expect(screen.getByRole('button', { name: 'Record a check' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
  });

  it('can record without reviewing, and review without recording', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(
      list([check()], { can_record_result: false, can_review: true }),
    );
    renderChecks();
    await screen.findByTestId('buyer-check');
    expect(screen.queryByRole('button', { name: 'Record a check' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
  });

  it('does not offer a review of a check with no outcome yet', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue(list([check({ status: 'PENDING' })]));
    renderChecks();
    const row = await screen.findByTestId('buyer-check');
    expect(within(row).queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
    expect(row).toHaveTextContent('This check has no outcome yet');
  });
});

describe('BuyerChecks — recording a check', () => {
  async function openForm() {
    renderChecks();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a check' }));
    return screen.getByTestId('manual-result-form');
  }

  it('refuses a passed check with no evidence before calling the server', async () => {
    const form = await openForm();
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'A passed check needs evidence',
    );
    expect(triggerVerification).not.toHaveBeenCalled();
  });

  it('records a manual check on the buyer with its evidence', async () => {
    vi.mocked(triggerVerification).mockResolvedValue(check());
    const form = await openForm();
    fireEvent.change(within(form).getByLabelText('Check'), { target: { value: 'KYB' } });
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.change(within(form).getByLabelText('Risk'), { target: { value: 'LOW' } });
    fireEvent.change(within(form).getByLabelText('Evidence note'), {
      target: { value: '  Registry extract seen  ' },
    });
    fireEvent.change(within(form).getByLabelText('Evidence link'), {
      target: { value: 'https://registry.example/entity/1' },
    });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    await waitFor(() => expect(triggerVerification).toHaveBeenCalledTimes(1));
    expect(triggerVerification).toHaveBeenCalledWith({
      verification_type: 'KYB',
      provider: 'manual',
      payload: { status: 'PASSED', risk_level: 'LOW' },
      evidence_note: 'Registry extract seen',
      evidence_refs: [{ type: 'url', ref: 'https://registry.example/entity/1' }],
      entity_type: 'BUYER',
      entity_reference: BUYER_ID,
    });
    await waitFor(() => expect(screen.queryByTestId('manual-result-form')).not.toBeInTheDocument());
  });

  it('offers only the deal documents that can be opened as evidence', async () => {
    vi.mocked(listDealDocuments).mockResolvedValue({
      documents: [
        document(),
        document({
          id: '55555555-5555-4555-8555-555555555555',
          file_name: 'still-scanning.pdf',
          scan_status: 'PENDING_SCAN',
        }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    vi.mocked(triggerVerification).mockResolvedValue(check());
    const form = await openForm();

    fireEvent.click(await within(form).findByLabelText('registry-extract.pdf'));
    expect(within(form).queryByText('still-scanning.pdf')).not.toBeInTheDocument();
    expect(listDealDocuments).toHaveBeenCalledWith(DEAL_ID, {});

    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    await waitFor(() => expect(triggerVerification).toHaveBeenCalledTimes(1));
    expect(triggerVerification).toHaveBeenCalledWith(
      expect.objectContaining({
        evidence_note: null,
        evidence_refs: [{ type: 'document', ref: document().id }],
      }),
    );
  });

  it('shows the server’s refusal, e.g. a closed deal', async () => {
    vi.mocked(triggerVerification).mockRejectedValue(
      new ApiError(409, 'Deal is HANDED_OVER: no new check can be recorded', 'DEAL_CLOSED'),
    );
    const form = await openForm();
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'FAILED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('Deal is HANDED_OVER');
  });
});

describe('BuyerChecks — reviewing a check', () => {
  it('records a first review naming no earlier one', async () => {
    vi.mocked(reviewVerification).mockResolvedValue(check());
    renderChecks();
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'ACCEPTED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));

    await waitFor(() => expect(reviewVerification).toHaveBeenCalledTimes(1));
    expect(reviewVerification).toHaveBeenCalledWith(RESULT_ID, {
      review_status: 'ACCEPTED',
      note: null,
      supersedes_review_id: null,
    });
  });

  it('changes a verdict only by superseding the current review, with a reason', async () => {
    const current = review();
    vi.mocked(listVerificationResults).mockResolvedValue(
      list([
        check({
          review_status: 'ACCEPTED',
          latest_review_id: current.id,
          reviews: [current],
        }),
      ]),
    );
    vi.mocked(reviewVerification).mockResolvedValue(check());
    renderChecks();
    fireEvent.click(await screen.findByRole('button', { name: 'Change the verdict' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'REJECTED' } });

    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'Say why the verdict changes.',
    );
    expect(reviewVerification).not.toHaveBeenCalled();

    fireEvent.change(within(form).getByLabelText('Review note'), {
      target: { value: 'Registry mismatch' },
    });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));
    await waitFor(() => expect(reviewVerification).toHaveBeenCalledTimes(1));
    expect(reviewVerification).toHaveBeenCalledWith(RESULT_ID, {
      review_status: 'REJECTED',
      note: 'Registry mismatch',
      supersedes_review_id: current.id,
    });
  });

  it('reloads and explains when someone else reviewed first', async () => {
    vi.mocked(reviewVerification).mockRejectedValue(
      new ApiError(409, 'A review must supersede the current review', 'VERIFICATION_REVIEW_STALE'),
    );
    renderChecks();
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'ACCEPTED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'Someone else reviewed this check first',
    );
    await waitFor(() => expect(listVerificationResults).toHaveBeenCalledTimes(2));
  });

  it('shows any other refusal as the server words it', async () => {
    vi.mocked(reviewVerification).mockRejectedValue(
      new ApiError(
        409,
        'Verification result has a legacy review (ACCEPTED) with no review record to supersede.',
        'VERIFICATION_LEGACY_REVIEW_UNCHAINED',
      ),
    );
    renderChecks();
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'REJECTED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('legacy review');
  });
});
