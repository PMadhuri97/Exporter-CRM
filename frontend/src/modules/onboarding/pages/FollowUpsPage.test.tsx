/**
 * The Follow-ups screen.
 *
 * Most of these assert what the page does **not** decide. `state` and `is_overdue`
 * come from the server, which derives them from whether a completion row exists; the
 * page renders them. So the interesting cases are the ones where the server says
 * something and the screen follows — including a row the page would be wrong to offer
 * a button on.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import { completeFollowUp, listFollowUps } from '../api';
import type { CheckBack, FollowUp, FollowUpList } from '../types';

import { FollowUpsPage } from './FollowUpsPage';

// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({
  listFollowUps: vi.fn(),
  completeFollowUp: vi.fn(),
}));

const CUSTOMER_ID = '11111111-1111-4111-8111-111111111111';
const USER_ID = '22222222-2222-4222-8222-222222222222';

const OVERDUE: FollowUp = {
  activity_id: '33333333-3333-4333-8333-333333333333',
  customer_id: CUSTOMER_ID,
  exporter_display_name: 'Coastal Seafood Exports Pvt Ltd',
  activity_type: 'FOLLOW_UP',
  subject: 'Send the Dubai order indicative terms',
  notes: 'They are waiting on us.',
  actor_id: 'user-1',
  occurred_at: '2026-09-14T10:00:00Z',
  due_at: '2026-09-21T10:00:00Z',
  is_overdue: true,
  state: 'OVERDUE',
  completion: null,
};

const DONE: FollowUp = {
  ...OVERDUE,
  activity_id: '44444444-4444-4444-8444-444444444444',
  subject: 'Introductory call with the export manager',
  notes: null,
  is_overdue: false,
  state: 'DONE',
  completion: {
    id: '55555555-5555-4555-8555-555555555555',
    outcome: 'RESCHEDULED',
    note: 'They asked for another three weeks.',
    next_due_at: '2026-10-18T10:00:00Z',
    completed_by: USER_ID,
    completed_at: '2026-09-26T09:00:00Z',
  },
};

const CHECK_BACK: CheckBack = {
  customer_id: '66666666-6666-4666-8666-666666666666',
  exporter_display_name: 'Aarav Textiles Pvt Ltd',
  conversation: 'NOT_NOW',
  check_back_on: '2026-11-11',
  is_overdue: false,
};

function list(over: Partial<FollowUpList> = {}): FollowUpList {
  return {
    follow_ups: [OVERDUE],
    follow_ups_total: 1,
    check_backs: [CHECK_BACK],
    check_backs_total: 1,
    limit: 50,
    offset: 0,
    ...over,
  };
}

function mockUser(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: USER_ID,
    email: 'someone@example.com',
    role,
  } as never);
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FollowUpsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('FollowUpsPage', () => {
  beforeEach(() => {
    mockUser('OPERATIONS');
    vi.mocked(listFollowUps).mockResolvedValue(list());
    vi.mocked(completeFollowUp).mockResolvedValue(DONE.completion!);
  });

  it('shows a loading state before the list arrives', () => {
    renderPage();
    expect(screen.getByRole('heading', { name: 'Follow-ups', level: 1 })).toBeInTheDocument();
    expect(screen.queryByTestId('follow-up-row')).not.toBeInTheDocument();
  });

  it('opens on Overdue and asks the server for that state', async () => {
    renderPage();
    await screen.findByTestId('follow-up-row');
    expect(listFollowUps).toHaveBeenCalledWith(
      expect.objectContaining({ state: 'OVERDUE', actorId: undefined }),
    );
  });

  it('shows the state the server sent, not one it works out', async () => {
    // A row the server calls DONE is shown as done even though its due date is past —
    // the page must not re-derive "overdue" from the date.
    vi.mocked(listFollowUps).mockResolvedValue(
      list({ follow_ups: [DONE], follow_ups_total: 1 }),
    );
    renderPage();
    expect(await screen.findByTestId('follow-up-state')).toHaveTextContent('Done');
  });

  it('shows a completion with who recorded it and where it was moved to', async () => {
    vi.mocked(listFollowUps).mockResolvedValue(
      list({ follow_ups: [DONE], follow_ups_total: 1 }),
    );
    renderPage();
    const row = await screen.findByTestId('follow-up-row');
    expect(within(row).getByText(/Rescheduled/)).toBeInTheDocument();
    expect(within(row).getByText(/moved to/)).toBeInTheDocument();
    expect(
      within(row).getByText('They asked for another three weeks.'),
    ).toBeInTheDocument();
  });

  it('names who completed a follow-up, not their account id (R-59)', async () => {
    vi.mocked(listFollowUps).mockResolvedValue(
      list({
        follow_ups: [
          { ...DONE, completion: { ...DONE.completion!, completed_by_name: 'Priya Ops' } },
        ],
        follow_ups_total: 1,
      }),
    );
    renderPage();
    const row = await screen.findByTestId('follow-up-row');
    expect(within(row).getByText(/by Priya Ops on/)).toBeInTheDocument();
    expect(within(row).queryByText(new RegExp(USER_ID))).not.toBeInTheDocument();
  });

  it('falls back to a shortened id when no name is served, as other screens do', async () => {
    // DEVELOPER is not given an unnamed account's email, so the name can be null.
    vi.mocked(listFollowUps).mockResolvedValue(
      list({
        follow_ups: [{ ...DONE, completion: { ...DONE.completion!, completed_by_name: null } }],
        follow_ups_total: 1,
      }),
    );
    renderPage();
    const row = await screen.findByTestId('follow-up-row');
    expect(within(row).getByText(/by User 22222222… on/)).toBeInTheDocument();
    expect(within(row).queryByText(new RegExp(USER_ID))).not.toBeInTheDocument();
  });

  it('offers no way to complete a follow-up that is already done', async () => {
    vi.mocked(listFollowUps).mockResolvedValue(
      list({ follow_ups: [DONE], follow_ups_total: 1 }),
    );
    renderPage();
    await screen.findByTestId('follow-up-row');
    // A second completion is refused by the server; not offering it is the screen's
    // half of that rule.
    expect(screen.queryByRole('button', { name: 'Mark done' })).not.toBeInTheDocument();
  });

  it('records an outcome and sends no next due date for a closing one', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Mark done' }));
    fireEvent.change(screen.getByLabelText(/^Note$/), {
      target: { value: 'Sent the terms' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record' }));

    await waitFor(() =>
      expect(completeFollowUp).toHaveBeenCalledWith(OVERDUE.activity_id, {
        outcome: 'DONE',
        note: 'Sent the terms',
        next_due_at: null,
      }),
    );
  });

  it('asks for a new due date only when rescheduling, and says what that does', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Mark done' }));
    expect(screen.queryByLabelText(/New due date/)).not.toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'RESCHEDULED' } });
    expect(screen.getByLabelText(/New due date/)).toBeRequired();
    // The rule stated where the person is about to act on it: the old activity is
    // never edited, so rescheduling creates a second follow-up.
    expect(screen.getByText(/logs a new follow-up/)).toBeInTheDocument();
  });

  it('sends the new due date when rescheduling', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Mark done' }));
    fireEvent.change(screen.getByLabelText('Outcome'), { target: { value: 'RESCHEDULED' } });
    fireEvent.change(screen.getByLabelText(/New due date/), {
      target: { value: '2027-01-15T09:00' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Record' }));

    await waitFor(() =>
      expect(completeFollowUp).toHaveBeenLastCalledWith(
        OVERDUE.activity_id,
        expect.objectContaining({ outcome: 'RESCHEDULED' }),
      ),
    );
    // The exact instant depends on the runner's timezone, so assert that one was sent
    // rather than which — pinning it would make this test fail in another timezone
    // while the behaviour was correct. `lastCall`, not `calls[0]`: this project does
    // not set `clearMocks`, so `vi.fn()`s keep every call made in the file.
    const [, payload] = vi.mocked(completeFollowUp).mock.lastCall!;
    expect(payload.next_due_at).toBeTruthy();
  });

  it('shows the server refusal as the server worded it', async () => {
    vi.mocked(completeFollowUp).mockRejectedValue(
      new Error('Follow-up was already completed as DONE'),
    );
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Mark done' }));
    fireEvent.click(screen.getByRole('button', { name: 'Record' }));
    // The form stays open on failure, so the person can see what happened and retry
    // rather than losing what they typed.
    await waitFor(() => expect(completeFollowUp).toHaveBeenCalled());
    expect(screen.getByRole('button', { name: 'Record' })).toBeInTheDocument();
  });

  it('narrows to one person without gating the list', async () => {
    renderPage();
    await screen.findByTestId('follow-up-row');
    fireEvent.click(screen.getByRole('radio', { name: 'Mine' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ actorId: USER_ID }),
      ),
    );
  });

  it('switches state by asking the server, not by filtering in the browser', async () => {
    renderPage();
    await screen.findByTestId('follow-up-row');
    fireEvent.click(screen.getByRole('tab', { name: 'Done' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'DONE' }),
      ),
    );
  });

  it('shows check-backs as their own section, with no way to complete them', async () => {
    renderPage();
    const row = await screen.findByTestId('check-back-row');
    expect(within(row).getByText('Aarav Textiles Pvt Ltd')).toBeInTheDocument();
    expect(within(row).getByText(/Check back/)).toBeInTheDocument();
    // A check-back is dealt with by moving the conversation gauge on the company's
    // page. There is no completion for it and the screen must not imply one.
    expect(within(row).queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText(/move the\s+conversation on the company's page/)).toBeInTheDocument();
  });

  it('leaves check-backs out of the tabs where they would be noise', async () => {
    renderPage();
    await screen.findByTestId('check-back-row');
    fireEvent.click(screen.getByRole('tab', { name: 'Outstanding' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ includeCheckBacks: false }),
      ),
    );
    expect(screen.queryByTestId('check-back-row')).not.toBeInTheDocument();
  });

  it('shows an empty state that says what a follow-up is', async () => {
    vi.mocked(listFollowUps).mockResolvedValue(
      list({ follow_ups: [], follow_ups_total: 0, check_backs: [], check_backs_total: 0 }),
    );
    renderPage();
    expect(await screen.findByText(/Nothing is overdue/)).toBeInTheDocument();
    // Overdue lists only the check-backs that are due, and says so when there are none.
    expect(screen.getByText(/No check-back is due yet/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'All' }));
    expect(
      await screen.findByText(/No company is parked waiting for a check-back/),
    ).toBeInTheDocument();
  });

  it('asks for only the due check-backs on Overdue, and every one on All', async () => {
    renderPage();
    await screen.findByTestId('follow-up-row');
    expect(listFollowUps).toHaveBeenLastCalledWith(
      expect.objectContaining({ state: 'OVERDUE', checkBacksDueOnly: true }),
    );
    expect(screen.getByRole('heading', { name: /^Check-backs due/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: 'All' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: undefined, checkBacksDueOnly: false }),
      ),
    );
  });

  it('shows no pager when everything fits on one page', async () => {
    renderPage();
    await screen.findByTestId('follow-up-row');
    expect(screen.queryByTestId('follow-ups-pager')).not.toBeInTheDocument();
  });

  it('pages through a long list, and a new tab starts from its first page', async () => {
    vi.mocked(listFollowUps).mockResolvedValue(list({ follow_ups_total: 120 }));
    renderPage();
    const pager = await screen.findByTestId('follow-ups-pager');
    expect(within(pager).getByText('1–1 of 120')).toBeInTheDocument();
    expect(within(pager).getByRole('button', { name: 'Previous' })).toBeDisabled();

    fireEvent.click(within(pager).getByRole('button', { name: 'Next' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ limit: 50, offset: 50 }),
      ),
    );

    fireEvent.click(screen.getByRole('tab', { name: 'Done' }));
    await waitFor(() =>
      expect(listFollowUps).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: 'DONE', offset: 0 }),
      ),
    );
  });

  it('shows an error state carrying the server message', async () => {
    vi.mocked(listFollowUps).mockRejectedValue(new Error('the database is down'));
    renderPage();
    expect(
      await screen.findByText(/Could not load follow-ups\. the database is down/),
    ).toBeInTheDocument();
  });

  it('gives DEVELOPER the list and no way to record anything', async () => {
    mockUser('DEVELOPER');
    renderPage();
    await screen.findByTestId('follow-up-row');
    expect(screen.queryByRole('button', { name: 'Mark done' })).not.toBeInTheDocument();
  });

  it('links each row to its company', async () => {
    renderPage();
    const row = await screen.findByTestId('follow-up-row');
    expect(
      within(row).getByRole('link', { name: /Coastal Seafood Exports Pvt Ltd/ }),
    ).toHaveAttribute('href', `/companies/${CUSTOMER_ID}`);
  });
});
