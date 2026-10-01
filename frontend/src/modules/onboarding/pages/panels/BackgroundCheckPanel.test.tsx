import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import {
  getBackgroundCheck,
  listBackgroundCheckDecisions,
  recordBackgroundCheckDecision,
  startCheckCycle,
} from '../../api';
import type { BackgroundCheck, BackgroundCheckDecision } from '../../types';

import { BackgroundCheckPanel } from './BackgroundCheckPanel';

vi.mock('../../api', () => ({
  getBackgroundCheck: vi.fn(),
  listBackgroundCheckDecisions: vi.fn(),
  recordBackgroundCheckDecision: vi.fn(),
  startCheckCycle: vi.fn(),
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
    compliance: {
      is_clear: false,
      clear_expires_at: null,
      is_clear_current: false,
      sanctions: 'MISSING',
      aml: 'MISSING',
    },
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
        // The value on screen, so a move made from a stale screen is refused (409).
        from_value: 'IN_REVIEW',
      }),
    );
  });

  it('drops a risk chosen for CLEAR when another move is chosen instead', async () => {
    // Decisions are append-only: a hidden rating riding along on a FLAGGED decision
    // could never be taken back, and would show as the company's risk.
    vi.mocked(recordBackgroundCheckDecision).mockResolvedValue(decision());
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Clear this company/));
    fireEvent.change(screen.getByLabelText('Risk rating'), { target: { value: 'LOW' } });
    fireEvent.click(screen.getByLabelText(/Flag this company/));
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'sanctions hit' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));

    await waitFor(() =>
      expect(recordBackgroundCheckDecision).toHaveBeenCalledWith(COMPANY_ID, {
        to_value: 'FLAGGED',
        reason: 'sanctions hit',
        risk_rating: null,
        from_value: 'IN_REVIEW',
      }),
    );
  });

  it('starts the risk rating afresh when CLEAR is chosen again', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Clear this company/));
    fireEvent.change(screen.getByLabelText('Risk rating'), { target: { value: 'HIGH' } });
    fireEvent.click(screen.getByLabelText(/Flag this company/));
    fireEvent.click(screen.getByLabelText(/Clear this company/));

    expect(screen.getByLabelText('Risk rating')).toHaveValue('');
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

  it('says what each outstanding prerequisite asks for, not its key', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ clear_blocked_reasons: ['no_checks_pending', 'screening_items_answered'] }),
    );
    renderPanel();

    const note = await screen.findByText(/Before this company can be cleared/);
    expect(note).toHaveTextContent(/every verification check needs a final answer/);
    expect(note).toHaveTextContent(/every screening item must be passed or exempt/);
    expect(note).not.toHaveTextContent('no_checks_pending');
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

  it("shows the server's reason for a refusal and reloads the standing", async () => {
    vi.mocked(recordBackgroundCheckDecision).mockRejectedValue(
      new ApiError(
        409,
        'The background check for company x is now CLEAR, not IN_REVIEW. Reload it and decide again',
        'BACKGROUND_CHECK_STATE_CHANGED',
      ),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    const loads = vi.mocked(getBackgroundCheck).mock.calls.length;
    fireEvent.click(screen.getByLabelText(/Flag this company/));
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'reason' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/is now CLEAR, not IN_REVIEW/);
    await waitFor(() =>
      expect(vi.mocked(getBackgroundCheck).mock.calls.length).toBeGreaterThan(loads),
    );
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

  it('says who decided by name, and when in the app’s one date format', async () => {
    vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
      decisions: [
        decision({
          decided_by: 'cc56991e-0000-4000-8000-000000000001',
          decided_by_name: 'Meera Compliance',
          decided_at: '2026-09-28T10:00:00Z',
        }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderPanel();

    const row = await screen.findByTestId('decision-row');
    expect(row).toHaveTextContent('Meera Compliance');
    expect(row).not.toHaveTextContent('cc56991e');
    // `formatDateTime` ("28 Sep 2026, …"), not the browser's `toLocaleString`.
    expect(row).toHaveTextContent(/28 Sep 2026, \d\d:\d\d/);
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

describe('BackgroundCheckPanel — check cycles and expiry (Developer 1)', () => {
  const currentCycle = {
    id: 'cycle-1',
    company_id: COMPANY_ID,
    number: 1,
    kind: 'INITIAL',
    reason: null,
    started_at: '2026-09-01T09:00:00Z',
    started_by: 'x',
    started_by_name: null,
    source: 'MIGRATION',
    rules_version: null,
    is_current: true,
  };

  it('names the current cycle and the Clear expiry', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        value: 'CLEAR',
        allowed_moves: [],
        current_cycle: currentCycle,
        compliance: {
          is_clear: true,
          clear_expires_at: '2027-09-28T10:00:00Z',
          is_clear_current: true,
          sanctions: 'PASSED',
          aml: 'PASSED',
        },
      }),
    );
    renderPanel();
    expect(await screen.findByTestId('current-cycle')).toHaveTextContent(
      'Cycle 1 · Initial check · started 01 Sep 2026',
    );
    expect(screen.getByTestId('clear-expiry')).toHaveTextContent('Clear until 28 Sep 2027');
  });

  it('offers exactly the Re-KYC / Re-KYB the server allows, and none when it allows none', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(standing({ allowed_cycle_actions: [] }));
    renderPanel();
    await screen.findByTestId('background-check-gauge');
    expect(screen.queryByTestId('check-cycle-actions')).not.toBeInTheDocument();
  });

  it('starts a Re-KYC with a reason, warning first that a Clear company is reopened', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        value: 'CLEAR',
        allowed_moves: [],
        current_cycle: currentCycle,
        allowed_cycle_actions: [
          { kind: 'RE_KYC', reason_required: true, reopens: true },
          { kind: 'RE_KYB', reason_required: true, reopens: true },
        ],
      }),
    );
    vi.mocked(startCheckCycle).mockResolvedValue({
      cycle: { ...currentCycle, id: 'cycle-2', number: 2, kind: 'RE_KYC', reason: 'Annual review' },
      reopen_decision: null,
    });
    renderPanel();
    expect(await screen.findByRole('button', { name: 'Start Re-KYB' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start Re-KYC' }));
    const dialog = screen.getByRole('dialog', { name: 'Start Re-KYC' });
    expect(dialog).toHaveTextContent('moves the check back to In review');
    const submit = within(dialog).getByRole('button', { name: 'Start Re-KYC' });
    expect(submit).toBeDisabled(); // a reason is required
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: ' Annual review ' } });
    fireEvent.click(submit);
    await waitFor(() =>
      expect(startCheckCycle).toHaveBeenCalledWith(COMPANY_ID, {
        kind: 'RE_KYC',
        reason: 'Annual review',
      }),
    );
  });

  it('shows the server’s refusal of a start', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ allowed_cycle_actions: [{ kind: 'RE_KYB', reason_required: true, reopens: false }] }),
    );
    vi.mocked(startCheckCycle).mockRejectedValue(
      new ApiError(409, 'Check cycle 1 has nothing recorded in it yet', 'CHECK_CYCLE_EMPTY'),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Start Re-KYB' }));
    const dialog = screen.getByRole('dialog', { name: 'Start Re-KYB' });
    expect(dialog).not.toHaveTextContent('moves the check back');
    fireEvent.change(within(dialog).getByLabelText('Reason'), { target: { value: 'New owner' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Start Re-KYB' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('nothing recorded');
  });
});
