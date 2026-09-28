import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { reviewVerification } from '../api';
import type { VerificationResult } from '../types';

import { ReviewChain, ReviewDialog } from './ReviewDialog';
import {
  COMPANY_ID,
  RESULT_ID,
  renderWithClient,
  review,
  verificationResult,
} from '../testing/verification-fixtures';

vi.mock('../api', () => ({
  reviewVerification: vi.fn(),
}));

const onStale = vi.fn();

function renderDialog(result: VerificationResult, canReview = true) {
  return renderWithClient(
    <ReviewDialog
      result={result}
      entityType="EXPORTER"
      entityReference={COMPANY_ID}
      canReview={canReview}
      onStale={onStale}
    />,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(reviewVerification).mockResolvedValue(verificationResult());
});

describe('ReviewChain', () => {
  it('shows every review, first to current, as recorded', () => {
    const first = review();
    const second = review({
      id: '55555555-5555-4555-8555-555555555555',
      review_status: 'REJECTED',
      reviewed_by: 'legacy-officer',
      reviewed_at: '2026-09-28T11:00:00Z',
      note: 'Registry mismatch',
      supersedes_review_id: first.id,
    });
    render(<ReviewChain reviews={[first, second]} />);

    const entries = screen.getAllByTestId('review-chain-entry');
    expect(entries).toHaveLength(2);
    expect(entries[0]).toHaveTextContent('Accepted');
    expect(entries[0]).toHaveTextContent('Superseded');
    // A user id is shortened and labelled, never shown raw.
    expect(entries[0]).toHaveTextContent('User 22222222…');
    expect(entries[0]).toHaveTextContent('28 Sep 2026');
    expect(entries[1]).toHaveTextContent('Rejected');
    expect(entries[1]).toHaveTextContent('Current');
    expect(entries[1]).toHaveTextContent('legacy-officer');
    expect(entries[1]).toHaveTextContent('Registry mismatch');
  });

  it('renders nothing when a result has no review', () => {
    const { container } = render(<ReviewChain reviews={[]} />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe('ReviewDialog — who may review, and what', () => {
  it('offers nothing when the server says the caller may not review', () => {
    const { container } = renderDialog(verificationResult(), false);
    expect(container).toBeEmptyDOMElement();
  });

  it('does not offer a review of a PENDING result', () => {
    renderDialog(verificationResult({ status: 'PENDING' }));
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
    expect(screen.getByText(/has no outcome yet/)).toBeInTheDocument();
  });

  it('says a placeholder was never run, rather than that it is in flight', () => {
    renderDialog(verificationResult({ status: 'PENDING', is_placeholder: true }));
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
    expect(screen.getByText(/no provider ran this check/)).toBeInTheDocument();
  });
});

describe('ReviewDialog — recording', () => {
  it('records a first review naming no earlier one', async () => {
    renderDialog(verificationResult());
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    const form = screen.getByTestId('review-form');

    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Choose a verdict.');
    expect(reviewVerification).not.toHaveBeenCalled();

    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'ACCEPTED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));
    await waitFor(() => expect(reviewVerification).toHaveBeenCalledTimes(1));
    expect(reviewVerification).toHaveBeenCalledWith(RESULT_ID, {
      review_status: 'ACCEPTED',
      note: null,
      supersedes_review_id: null,
    });
    await waitFor(() => expect(screen.queryByTestId('review-form')).not.toBeInTheDocument());
  });

  it('supersedes the current review, and only with a reason', async () => {
    const current = review();
    renderDialog(
      verificationResult({ review_status: 'ACCEPTED', latest_review_id: current.id, reviews: [current] }),
    );
    fireEvent.click(screen.getByRole('button', { name: 'Change the verdict' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'REJECTED' } });

    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Say why the verdict changes.');
    expect(reviewVerification).not.toHaveBeenCalled();

    fireEvent.change(within(form).getByLabelText('Review note'), {
      target: { value: '  UBO is a PEP  ' },
    });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));
    await waitFor(() => expect(reviewVerification).toHaveBeenCalledTimes(1));
    expect(reviewVerification).toHaveBeenCalledWith(RESULT_ID, {
      review_status: 'REJECTED',
      note: 'UBO is a PEP',
      supersedes_review_id: current.id,
    });
  });

  it('refetches and explains when another review was recorded first', async () => {
    vi.mocked(reviewVerification).mockRejectedValue(
      new ApiError(409, 'A review must supersede the current review', 'VERIFICATION_REVIEW_STALE'),
    );
    renderDialog(verificationResult());
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'ESCALATED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'Someone else reviewed this check first',
    );
    expect(onStale).toHaveBeenCalledTimes(1);
    // The form stays open: nothing was overwritten, and the reviewer decides again.
    expect(screen.getByTestId('review-form')).toBeInTheDocument();
  });

  it('shows any other refusal as the server words it, without refetching', async () => {
    vi.mocked(reviewVerification).mockRejectedValue(
      new ApiError(422, 'Verification result is still PENDING', 'VERIFICATION_RESULT_NOT_REVIEWABLE'),
    );
    renderDialog(verificationResult());
    fireEvent.click(screen.getByRole('button', { name: 'Review' }));
    const form = screen.getByTestId('review-form');
    fireEvent.change(within(form).getByLabelText('Verdict'), { target: { value: 'ACCEPTED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record review' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('still PENDING');
    expect(onStale).not.toHaveBeenCalled();
  });
});
