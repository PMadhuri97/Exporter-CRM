import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getBackgroundCheck,
  listBackgroundCheckDecisions,
  recordBackgroundCheckDecision,
} from '../../api';
import type { BackgroundCheck, BackgroundCheckDecision } from '../../types';

import { BackgroundCheckPanel } from './BackgroundCheckPanel';

vi.mock('../../api', () => ({
  getBackgroundCheck: vi.fn(),
  listBackgroundCheckDecisions: vi.fn(),
  recordBackgroundCheckDecision: vi.fn(),
}));

// Developer 4B's section. Stubbed so this file tests the gauge, not their 631-line
// component — but still asserted to be rendered, because the panel must not drop it.
vi.mock('../../components/VerificationSection', () => ({
  VerificationSection: () => <div data-testid="verification-section" />,
}));

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function standing(overrides: Partial<BackgroundCheck> = {}): BackgroundCheck {
  return {
    company_id: COMPANY_ID,
    value: 'IN_REVIEW',
    risk_rating: null,
    latest_decision_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    clearing_decision_id: null,
    decided_at: '2026-09-28T10:00:00Z',
    allowed_moves: [
      { to_value: 'CLEAR', reason_required: true, risk_required: true },
      { to_value: 'MORE_INFO', reason_required: true, risk_required: false },
      { to_value: 'FLAGGED', reason_required: true, risk_required: false },
    ],
    clear_blocked_reasons: [],
    ...overrides,
  };
}

function decision(overrides: Partial<BackgroundCheckDecision> = {}): BackgroundCheckDecision {
  return {
    id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    company_id: COMPANY_ID,
    from_value: 'NOT_STARTED',
    to_value: 'IN_REVIEW',
    decided_by: 'compliance-user',
    decided_by_kind: 'MANUAL',
    source: 'MANUAL',
    decided_at: '2026-09-28T10:00:00Z',
    reason: null,
    risk_rating: null,
    supersedes_decision_id: null,
    evidence: [],
    ...overrides,
  };
}

function renderPanel(isStaff = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BackgroundCheckPanel customerId={COMPANY_ID} isStaff={isStaff} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getBackgroundCheck).mockResolvedValue(standing());
  vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
    decisions: [decision()],
    total: 1,
    limit: 50,
    offset: 0,
  });
});

describe('BackgroundCheckPanel — the gauge', () => {
  it('shows the current value with an honest description', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ value: 'NOT_STARTED', allowed_moves: [] }),
    );
    renderPanel();

    const gauge = await screen.findByTestId('background-check-gauge');
    expect(gauge).toHaveAttribute('data-value', 'NOT_STARTED');
    expect(screen.getByText('Not started')).toBeInTheDocument();
    // Never "pending" or "clear": no check has run, and the screen must not imply one has.
    expect(
      screen.getByText(/No background check has been started/),
    ).toBeInTheDocument();
  });

  it('shows a loading state first', () => {
    vi.mocked(getBackgroundCheck).mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.getByText('Loading the background check…')).toBeInTheDocument();
  });

  it('says so when the check cannot be loaded', async () => {
    vi.mocked(getBackgroundCheck).mockRejectedValue(new Error('boom'));
    renderPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The background check could not be loaded.',
    );
  });

  it('renders nothing for a non-staff viewer', () => {
    const { container } = renderPanel(false);
    expect(container).toBeEmptyDOMElement();
  });

  it('keeps Developer 4B’s verification section below the gauge', async () => {
    renderPanel();
    await screen.findByTestId('background-check-gauge');
    expect(screen.getByTestId('verification-section')).toBeInTheDocument();
  });
});

describe('BackgroundCheckPanel — risk', () => {
  it('makes CRITICAL visually distinct from the other ratings', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ value: 'CLEAR', risk_rating: 'CRITICAL', allowed_moves: [] }),
    );
    renderPanel();

    const chip = await screen.findByTestId('risk-chip');
    expect(chip).toHaveAttribute('data-risk', 'CRITICAL');
    // Filled and bold, unlike LOW/MEDIUM/HIGH, which are tinted only.
    expect(chip.className).toContain('bg-red-600');
    expect(chip.className).toContain('font-bold');
  });

  it('explains a risk shown on a company that is not clear', async () => {
    // D6 is open: a reopened company still reports the last recorded risk, so the
    // screen says where it came from rather than implying it describes the company now.
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ value: 'IN_REVIEW', risk_rating: 'HIGH' }),
    );
    renderPanel();

    expect(
      await screen.findByText(/from the most recent decision that set one/),
    ).toBeInTheDocument();
  });
});

describe('BackgroundCheckPanel — the move dialog', () => {
  it('offers only the moves the server returned', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        allowed_moves: [{ to_value: 'MORE_INFO', reason_required: true, risk_required: false }],
      }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));

    expect(screen.getByLabelText(/Ask for more information/)).toBeInTheDocument();
    // Absent because the server did not offer it — the screen keeps no move table.
    expect(screen.queryByLabelText(/Flag this company/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Clear this company/)).not.toBeInTheDocument();
  });

  it('offers nothing to record when the server allows no move', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(standing({ allowed_moves: [] }));
    renderPanel();

    await screen.findByTestId('background-check-gauge');
    expect(
      screen.queryByRole('button', { name: 'Record a decision' }),
    ).not.toBeInTheDocument();
  });

  it('will not submit until a required reason is given', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Flag this company/));

    const submit = screen.getByRole('button', { name: 'Record decision' });
    expect(submit).toBeDisabled();

    fireEvent.change(screen.getByLabelText('Reason'), {
      target: { value: 'a director matched a sanctions list' },
    });
    expect(submit).toBeEnabled();
  });

  it('asks for a risk rating exactly when the server requires one', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));

    fireEvent.click(screen.getByLabelText(/Flag this company/));
    expect(screen.queryByLabelText('Risk rating')).not.toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Clear this company/));
    expect(screen.getByLabelText('Risk rating')).toBeInTheDocument();
  });

  it('sends the decision the server asked for', async () => {
    vi.mocked(recordBackgroundCheckDecision).mockResolvedValue(decision());
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Flag this company/));
    fireEvent.change(screen.getByLabelText('Reason'), {
      target: { value: 'adverse media' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));

    await waitFor(() =>
      expect(recordBackgroundCheckDecision).toHaveBeenCalledWith(COMPANY_ID, {
        to_value: 'FLAGGED',
        reason: 'adverse media',
        risk_rating: null,
      }),
    );
  });

  it('refuses to submit a CLEAR whose prerequisites are outstanding, and says why', async () => {
    // The server offers CLEAR so the screen can explain; sending it would be a 409.
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ clear_blocked_reasons: ['screening_items_answered', 'evidence_recorded'] }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Clear this company/));

    expect(screen.getByText(/cannot be cleared yet/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeDisabled();
  });

  it('shows what is outstanding on the panel itself, before the dialog is opened', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ clear_blocked_reasons: ['no_checks_pending'] }),
    );
    renderPanel();

    expect(
      await screen.findByText(/Before this company can be cleared/),
    ).toBeInTheDocument();
  });

  it('reports a failed submission without closing the dialog', async () => {
    vi.mocked(recordBackgroundCheckDecision).mockRejectedValue(new Error('409'));
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Flag this company/));
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'reason' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The decision could not be recorded.',
    );
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeInTheDocument();
  });
});

describe('BackgroundCheckPanel — the decision trail', () => {
  it('lists each decision as a move, with its reason', async () => {
    vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
      decisions: [
        decision({
          from_value: 'IN_REVIEW',
          to_value: 'FLAGGED',
          reason: 'a director matched',
        }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderPanel();

    expect(await screen.findByText('In review → Flagged')).toBeInTheDocument();
    expect(screen.getByText('a director matched')).toBeInTheDocument();
  });

  it('summarises the evidence snapshot as counts, never contents', async () => {
    vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
      decisions: [
        decision({
          evidence: [
            { kind: 'DOCUMENT', crm_document_id: 'a', verification_result_id: null, verification_review_id: null, screening_review_item_id: null },
            { kind: 'SCREENING_ITEM', crm_document_id: null, verification_result_id: null, verification_review_id: null, screening_review_item_id: 'b' },
            { kind: 'SCREENING_ITEM', crm_document_id: null, verification_result_id: null, verification_review_id: null, screening_review_item_id: 'c' },
          ],
        }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderPanel();

    expect(await screen.findByTestId('evidence-summary')).toHaveTextContent(
      'Recorded against 1 document, 2 screening items.',
    );
  });

  it('says plainly when a decision recorded no evidence', async () => {
    renderPanel();
    expect(
      await screen.findByText('No evidence was recorded against this decision.'),
    ).toBeInTheDocument();
  });

  it('shows an empty state when nothing has been decided', async () => {
    vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
      decisions: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    renderPanel();

    expect(
      await screen.findByText('No decisions have been recorded for this company yet.'),
    ).toBeInTheDocument();
  });

  it('says so when the trail cannot be loaded', async () => {
    vi.mocked(listBackgroundCheckDecisions).mockRejectedValue(new Error('boom'));
    renderPanel();

    await waitFor(() =>
      expect(
        screen.getByText('The decision history could not be loaded.'),
      ).toBeInTheDocument(),
    );
  });
});
