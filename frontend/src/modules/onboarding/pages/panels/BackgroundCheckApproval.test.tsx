/**
 * Maker-checker, rule B and Re-KYC on the background-check panel — **Developer 1**
 * (plans P3-1c, P3-2, P3-3c).
 *
 * Everything asserted here is served: whether a proposal awaits approval and what this
 * user may do with it (`open_proposal.allowed_actions`), whether a move needs approval
 * (`approval_required`), the required checks and their state, and whether the Clear is
 * due for Re-KYC. The panel decides none of it.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import {
  approveBackgroundCheckProposal,
  getBackgroundCheck,
  listBackgroundCheckDecisions,
  recordBackgroundCheckDecision,
  rejectBackgroundCheckProposal,
  withdrawBackgroundCheckProposal,
} from '../../api';
import type {
  BackgroundCheck,
  BackgroundCheckDecision,
  BackgroundCheckProposal,
} from '../../types';

import { BackgroundCheckPanel } from './BackgroundCheckPanel';

vi.mock('../../api', () => ({
  approveBackgroundCheckProposal: vi.fn(),
  getBackgroundCheck: vi.fn(),
  listBackgroundCheckDecisions: vi.fn(),
  recordBackgroundCheckDecision: vi.fn(),
  rejectBackgroundCheckProposal: vi.fn(),
  startCheckCycle: vi.fn(),
  withdrawBackgroundCheckProposal: vi.fn(),
}));

vi.mock('../../components/VerificationSection', () => ({
  VerificationSection: () => <div data-testid="verification-section" />,
}));

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const PROPOSAL_ID = 'eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee';

function proposal(overrides: Partial<BackgroundCheckProposal> = {}): BackgroundCheckProposal {
  return {
    id: PROPOSAL_ID,
    company_id: COMPANY_ID,
    company_name: 'Coastal Seafood Exports',
    based_on_decision_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    from_value: 'IN_REVIEW',
    to_value: 'CLEAR',
    risk_rating: 'LOW',
    reason: 'Every check passed.',
    proposed_by: 'maker-id',
    proposed_by_name: 'Asha Maker',
    proposed_at: '2026-10-01T09:00:00Z',
    cycle_id: 'cycle-1',
    cycle_number: 1,
    rules_version: 'clear-2026-10-01-7items-kyb-aml-sanctions',
    evidence_count: 10,
    status: 'OPEN',
    resolved_by: null,
    resolved_by_name: null,
    resolved_at: null,
    resolution_reason: null,
    decision_id: null,
    stale_reason: null,
    allowed_actions: ['APPROVE', 'REJECT'],
    ...overrides,
  };
}

function standing(overrides: Partial<BackgroundCheck> = {}): BackgroundCheck {
  return {
    company_id: COMPANY_ID,
    value: 'IN_REVIEW',
    risk_rating: null,
    latest_decision_id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    clearing_decision_id: null,
    decided_at: '2026-09-28T10:00:00Z',
    allowed_moves: [
      { to_value: 'CLEAR', reason_required: true, risk_required: true, approval_required: true },
      { to_value: 'MORE_INFO', reason_required: true, risk_required: false, approval_required: false },
    ],
    clear_blocked_reasons: [],
    compliance: {
      is_clear: false,
      clear_expires_at: null,
      is_clear_current: false,
      sanctions: 'PASSED',
      aml: 'PASSED',
    },
    awaiting_approval: false,
    rekyc_due: false,
    required_checks: [
      { verification_type: 'KYB', state: 'PASSED' },
      { verification_type: 'AML', state: 'PASSED' },
      { verification_type: 'SANCTIONS', state: 'MISSING' },
    ],
    ...overrides,
  };
}

function awaiting(overrides: Partial<BackgroundCheckProposal> = {}): BackgroundCheck {
  return standing({
    allowed_moves: [],
    awaiting_approval: true,
    open_proposal: proposal(overrides),
  });
}

function decision(overrides: Partial<BackgroundCheckDecision> = {}): BackgroundCheckDecision {
  return {
    id: 'ffffffff-ffff-4fff-8fff-ffffffffffff',
    company_id: COMPANY_ID,
    from_value: 'IN_REVIEW',
    to_value: 'CLEAR',
    decided_by: 'maker-id',
    decided_by_name: 'Asha Maker',
    decided_by_kind: 'MANUAL',
    source: 'MANUAL',
    decided_at: '2026-10-01T10:00:00Z',
    reason: 'Every check passed.',
    risk_rating: 'LOW',
    supersedes_decision_id: null,
    evidence: [],
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <BackgroundCheckPanel customerId={COMPANY_ID} isStaff />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getBackgroundCheck).mockResolvedValue(standing());
  vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
    decisions: [],
    total: 0,
    limit: 50,
    offset: 0,
  });
});

describe('BackgroundCheckPanel — proposing (maker)', () => {
  it('says a CLEAR goes to a second officer and offers "Propose for approval"', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Clear this company/));

    expect(screen.getByTestId('approval-required-note')).toHaveTextContent(
      /second compliance officer/,
    );
    expect(screen.getByRole('button', { name: 'Propose for approval' })).toBeInTheDocument();
  });

  it('records a move that needs no approval as before', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Ask for more information/));

    expect(screen.queryByTestId('approval-required-note')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeInTheDocument();
  });

  it('sends a proposed CLEAR through the same request, then shows it awaiting approval', async () => {
    vi.mocked(recordBackgroundCheckDecision).mockResolvedValue(
      proposal({ allowed_actions: ['WITHDRAW'] }),
    );
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Record a decision' }));
    fireEvent.click(screen.getByLabelText(/Clear this company/));
    fireEvent.change(screen.getByLabelText('Risk rating'), { target: { value: 'LOW' } });
    fireEvent.change(screen.getByLabelText('Reason'), { target: { value: 'All passed' } });
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting({ allowed_actions: ['WITHDRAW'] }));
    fireEvent.click(screen.getByRole('button', { name: 'Propose for approval' }));

    await waitFor(() =>
      expect(recordBackgroundCheckDecision).toHaveBeenCalledWith(COMPANY_ID, {
        to_value: 'CLEAR',
        reason: 'All passed',
        risk_rating: 'LOW',
        from_value: 'IN_REVIEW',
      }),
    );
    expect(await screen.findByTestId('awaiting-approval')).toBeInTheDocument();
    expect(screen.getByTestId('awaiting-approval-badge')).toHaveTextContent('Awaiting approval');
  });
});

describe('BackgroundCheckPanel — awaiting approval', () => {
  it('shows the proposal and offers nothing else to record', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting());
    renderPanel();

    const section = await screen.findByTestId('awaiting-approval');
    expect(section).toHaveTextContent('Clear');
    expect(section).toHaveTextContent('Asha Maker');
    expect(section).toHaveTextContent('Every check passed.');
    expect(screen.getByTestId('background-check-gauge')).toHaveAttribute('data-value', 'IN_REVIEW');
    expect(
      screen.queryByRole('button', { name: 'Record a decision' }),
    ).not.toBeInTheDocument();
  });

  it('lets a second officer approve in two clicks', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting());
    vi.mocked(approveBackgroundCheckProposal).mockResolvedValue({
      decision: decision({ approved_by: 'checker-id', approved_by_name: 'Ravi Checker' }),
      proposal: proposal({ status: 'APPROVED' }),
    });
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    const dialog = screen.getByRole('dialog', { name: 'Approve this decision' });
    expect(dialog).toHaveTextContent(/decided by Asha Maker, approved by you/);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));

    await waitFor(() =>
      expect(approveBackgroundCheckProposal).toHaveBeenCalledWith(COMPANY_ID, PROPOSAL_ID),
    );
  });

  it('needs a reason to reject', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting());
    vi.mocked(rejectBackgroundCheckProposal).mockResolvedValue(proposal({ status: 'REJECTED' }));
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Reject' }));
    const dialog = screen.getByRole('dialog', { name: 'Reject this decision' });
    const confirm = within(dialog).getByRole('button', { name: 'Reject' });
    expect(confirm).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText('Reason'), {
      target: { value: ' The AML result needs a second look ' },
    });
    fireEvent.click(confirm);

    await waitFor(() =>
      expect(rejectBackgroundCheckProposal).toHaveBeenCalledWith(
        COMPANY_ID,
        PROPOSAL_ID,
        'The AML result needs a second look',
      ),
    );
  });

  it('offers the proposer only Withdraw, never Approve', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting({ allowed_actions: ['WITHDRAW'] }));
    vi.mocked(withdrawBackgroundCheckProposal).mockResolvedValue(
      proposal({ status: 'WITHDRAWN' }),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Withdraw' }));
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    const dialog = screen.getByRole('dialog', { name: 'Withdraw your proposal' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Withdraw' }));

    await waitFor(() =>
      expect(withdrawBackgroundCheckProposal).toHaveBeenCalledWith(COMPANY_ID, PROPOSAL_ID, null),
    );
  });

  it('says why an out-of-date proposal can only be rejected', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      awaiting({
        stale_reason: 'its inputs changed since it was proposed',
        allowed_actions: ['REJECT'],
      }),
    );
    renderPanel();

    expect(await screen.findByTestId('proposal-stale')).toHaveTextContent(
      /its inputs changed since it was proposed/,
    );
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument();
  });

  it('tells an RM that a second officer must decide, with no buttons', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting({ allowed_actions: [] }));
    renderPanel();

    const section = await screen.findByTestId('awaiting-approval');
    expect(section).toHaveTextContent(/A second compliance officer must approve or reject it/);
    expect(within(section).queryAllByRole('button')).toHaveLength(0);
  });

  it('shows the server’s refusal of an approval and keeps the dialog open', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(awaiting());
    vi.mocked(approveBackgroundCheckProposal).mockRejectedValue(
      new ApiError(
        409,
        'Proposal x is out of date (its inputs changed since it was proposed)',
        'BACKGROUND_CHECK_PROPOSAL_STALE',
      ),
    );
    renderPanel();

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }));
    const dialog = screen.getByRole('dialog', { name: 'Approve this decision' });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Approve' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/out of date/);
  });
});

describe('BackgroundCheckPanel — rule B, expiry and the trail', () => {
  it('lists the checks CLEAR requires, with their state in this cycle', async () => {
    renderPanel();
    const required = await screen.findByTestId('required-checks');
    expect(within(required).getByTestId('required-check-KYB')).toHaveAttribute('data-state', 'PASSED');
    expect(within(required).getByTestId('required-check-SANCTIONS')).toHaveAttribute(
      'data-state',
      'MISSING',
    );
  });

  it('words rule B’s outstanding prerequisites', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ clear_blocked_reasons: ['sanctions_passed'] }),
    );
    renderPanel();
    expect(await screen.findByText(/Before this company can be cleared/)).toHaveTextContent(
      'a sanctions check must have passed in this cycle',
    );
  });

  it('badges a Clear that is due for Re-KYC, without moving the gauge', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        value: 'CLEAR',
        allowed_moves: [],
        rekyc_due: true,
        compliance: {
          is_clear: true,
          clear_expires_at: '2026-09-30T10:00:00Z',
          is_clear_current: false,
          sanctions: 'PASSED',
          aml: 'PASSED',
        },
      }),
    );
    renderPanel();

    expect(await screen.findByTestId('rekyc-due-badge')).toHaveTextContent('Re-KYC due');
    expect(screen.getByTestId('background-check-gauge')).toHaveAttribute('data-value', 'CLEAR');
    expect(screen.getByTestId('clear-expiry')).toHaveTextContent(/expired/);
  });

  it('names who approved a decision, and until when a Clear is current', async () => {
    vi.mocked(listBackgroundCheckDecisions).mockResolvedValue({
      decisions: [
        decision({
          approved_by: 'checker-id',
          approved_by_name: 'Ravi Checker',
          approved_at: '2026-10-01T10:00:00Z',
          expires_at: '2027-10-01T10:00:00Z',
        }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderPanel();

    expect(await screen.findByTestId('decision-approved-by')).toHaveTextContent(
      'approved by Ravi Checker',
    );
    expect(screen.getByTestId('decision-expires')).toHaveTextContent(/Clear until/);
  });
});
