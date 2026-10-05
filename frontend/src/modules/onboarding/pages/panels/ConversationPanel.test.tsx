/**
 * The Conversation panel's gauge control and history.
 *
 * The panel is mounted directly rather than through `ExporterDetailPage`, because
 * what is under test is the gauge section and not the shell's query timing — the
 * page test owns that, and asserts it.
 *
 * The point of most of these tests is what the panel does **not** know. It holds no
 * value list, no transition table and no "NOT_NOW needs a date": the server serves
 * `allowed_moves`, and the panel renders exactly that. So the interesting cases are
 * the ones where the server says something unusual and the screen follows.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getExporterConversation,
  listConversationHistory,
  openDeal,
  setExporterConversation,
} from '../../api';
import type { Conversation, HistoryEntry, HistoryList } from '../../types';

import { ConversationPanel } from './ConversationPanel';

vi.mock('../../api', () => ({
  getExporterConversation: vi.fn(),
  setExporterConversation: vi.fn(),
  listConversationHistory: vi.fn(),
  addExporterContact: vi.fn(),
  logExporterActivity: vi.fn(),
  listExporterContacts: vi.fn(),
  listExporterActivities: vi.fn(),
  openDeal: vi.fn(),
}));

const CUSTOMER_ID = '11111111-1111-4111-8111-111111111111';

const PROSPECT: Conversation = {
  company_id: CUSTOMER_ID,
  conversation: 'SPOKE_TO_THEM',
  check_back_on: null,
  journey: 'PROSPECT',
  allowed_moves: [
    { to: 'INTERESTED', reason_required: false, check_back_required: false },
    { to: 'NOT_NOW', reason_required: true, check_back_required: true },
    { to: 'READY_NOW', reason_required: false, check_back_required: false },
  ],
};

const NO_HISTORY: HistoryList = { entries: [], total: 0, limit: 20, offset: 0 };

function renderPanel(props: Partial<Parameters<typeof ConversationPanel>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      {/* A router, because the READY_NOW prompt goes to the deal it opens. */}
      <MemoryRouter initialEntries={['/companies/c']}>
        <Routes>
          <Route path="/deals/:dealId" element={<p>Deal page</p>} />
          <Route
            path="*"
            element={
              <ConversationPanel
                customerId={CUSTOMER_ID}
                contacts={[]}
                contactsLoading={false}
                activities={[]}
                activitiesLoading={false}
                activitiesFetching={false}
                activityType=""
                onActivityTypeChange={() => {}}
                activityPage={0}
                onActivityPageChange={() => {}}
                hasNextActivityPage={false}
                isStaff
                {...props}
              />
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ConversationPanel — the conversation gauge', () => {
  beforeEach(() => {
    vi.mocked(getExporterConversation).mockResolvedValue(PROSPECT);
    vi.mocked(listConversationHistory).mockResolvedValue(NO_HISTORY);
    vi.mocked(setExporterConversation).mockResolvedValue({
      ...PROSPECT,
      conversation: 'INTERESTED',
    });
  });

  it('shows a loading state before the gauge arrives', () => {
    renderPanel();
    // Asserted through the section rather than a spinner role: the skeleton is a
    // pulsing block, which has no accessible name to find it by.
    expect(screen.getByText('Conversation')).toBeInTheDocument();
    expect(screen.queryByTestId('conversation-chip')).not.toBeInTheDocument();
  });

  it('shows the current value and exactly the moves the server served', async () => {
    renderPanel();
    expect(await screen.findByTestId('conversation-chip')).toHaveTextContent('Spoke To Them');
    expect(screen.getByRole('button', { name: /interested/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /not now/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /ready now/i })).toBeInTheDocument();
    // Not offered, because it is the current value — and because the server did
    // not list it. The panel does not compute that.
    expect(screen.queryByRole('button', { name: /spoke to them/i })).not.toBeInTheDocument();
  });

  it('asks for a check-back date only where the server says one is required', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /not now/i }));
    expect(screen.getByLabelText(/Check back on/)).toBeRequired();
    expect(screen.getByLabelText(/^Reason$/)).toBeRequired();

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByRole('button', { name: /interested/i }));
    expect(screen.queryByLabelText(/Check back on/)).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Reason \(optional\)/)).not.toBeRequired();
  });

  it('sends the check-back date with a NOT_NOW move', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /not now/i }));
    fireEvent.change(screen.getByLabelText(/Check back on/), {
      target: { value: '2027-01-15' },
    });
    fireEvent.change(screen.getByLabelText(/^Reason$/), {
      target: { value: 'Revisit after Q1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() =>
      expect(setExporterConversation).toHaveBeenCalledWith(CUSTOMER_ID, {
        conversation: 'NOT_NOW',
        reason: 'Revisit after Q1',
        check_back_on: '2027-01-15',
      }),
    );
  });

  it('never sends a check-back date on a move that does not take one', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /interested/i }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));

    await waitFor(() =>
      expect(setExporterConversation).toHaveBeenCalledWith(CUSTOMER_ID, {
        conversation: 'INTERESTED',
        reason: null,
        check_back_on: null,
      }),
    );
  });

  it('shows the check-back date when the conversation is NOT_NOW', async () => {
    vi.mocked(getExporterConversation).mockResolvedValue({
      ...PROSPECT,
      conversation: 'NOT_NOW',
      check_back_on: '2027-01-15',
      allowed_moves: [
        { to: 'READY_NOW', reason_required: false, check_back_required: false },
      ],
    });
    renderPanel();
    expect(await screen.findByText(/Check back on 15 Jan 2027/)).toBeInTheDocument();
  });

  it('offers to open a deal when the gauge reads READY_NOW, and goes to the new deal', async () => {
    vi.mocked(getExporterConversation).mockResolvedValue({
      ...PROSPECT,
      conversation: 'READY_NOW',
      allowed_moves: [],
    });
    vi.mocked(openDeal).mockResolvedValue({
      id: 'dddddddd-dddd-4ddd-8ddd-dddddddddddd',
    } as Awaited<ReturnType<typeof openDeal>>);
    renderPanel();
    // Seam S2: the prompt opens a deal through the same form the Deals tab uses.
    expect(
      await screen.findByText(/has something they want financed/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /open a deal/i }));
    fireEvent.change(screen.getByLabelText('Reference'), {
      target: { value: 'Rotterdam shipment' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Open deal' }));
    await waitFor(() =>
      expect(openDeal).toHaveBeenCalledWith(CUSTOMER_ID, { reference: 'Rotterdam shipment' }),
    );
    expect(await screen.findByText('Deal page')).toBeInTheDocument();
  });

  it('gives a reader who may not write no open-a-deal button', async () => {
    vi.mocked(getExporterConversation).mockResolvedValue({
      ...PROSPECT,
      conversation: 'READY_NOW',
      allowed_moves: [],
    });
    renderPanel({ isStaff: false });
    expect(
      await screen.findByText(/has something they want financed/),
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /open a deal/i })).not.toBeInTheDocument();
  });

  it('explains an empty move list on a LEAD as the gauge not applying yet', async () => {
    vi.mocked(getExporterConversation).mockResolvedValue({
      ...PROSPECT,
      conversation: 'NOT_CONTACTED',
      journey: 'LEAD',
      allowed_moves: [],
    });
    renderPanel();
    expect(
      await screen.findByText(/applies once this company is a prospect/),
    ).toBeInTheDocument();
  });

  it('offers no moves to a reader who may not set the gauge', async () => {
    // The server sends an empty list to DEVELOPER; the panel shows no buttons,
    // and does not have to know which role it is talking to.
    vi.mocked(getExporterConversation).mockResolvedValue({ ...PROSPECT, allowed_moves: [] });
    renderPanel({ isStaff: false });
    await screen.findByTestId('conversation-chip');
    expect(screen.queryByRole('button', { name: /interested/i })).not.toBeInTheDocument();
  });

  it('shows the history, newest first, with the reason and the check-back date', async () => {
    vi.mocked(listConversationHistory).mockResolvedValue({
      ...NO_HISTORY,
      total: 1,
      entries: [
        {
          id: '99999999-9999-4999-8999-999999999999',
          company_id: CUSTOMER_ID,
          deal_id: null,
          dimension: 'conversation',
          event_type: 'conversation_transition',
          from_value: 'INTERESTED',
          to_value: 'NOT_NOW',
          actor_id: 'user-1',
          reason: 'Budget frozen until April',
          source: 'conversation_service.set_conversation',
          // `HistoryEntryResponse.details` is `dict | None` on the server, which
          // openapi-typescript generates as `Record<string, never>` — a type that
          // accepts no properties at all. The cast is the narrowest way to build a
          // realistic row without touching the shared history schema, which is not
          // this panel's to retype. The panel reads the key defensively
          // (`typeof … === 'string'`) for the same reason.
          details: { check_back_on: '2027-04-01' } as unknown as HistoryEntry['details'],
          occurred_at: '2026-09-27T10:00:00Z',
        },
      ],
    });
    renderPanel();
    expect(await screen.findByText(/Interested →/)).toBeInTheDocument();
    expect(screen.getByText('Budget frozen until April')).toBeInTheDocument();
    expect(screen.getByText(/Check back 01 Apr 2027/)).toBeInTheDocument();
  });

  it('shows an empty state when nothing has been recorded', async () => {
    renderPanel();
    expect(
      await screen.findByText('No conversation changes recorded yet.'),
    ).toBeInTheDocument();
  });

  it('shows an error state, with the server message, when the gauge cannot be read', async () => {
    vi.mocked(getExporterConversation).mockRejectedValue(
      new Error('Exporter profile not found'),
    );
    renderPanel();
    expect(
      await screen.findByText(/Could not load the conversation\. Exporter profile not found/),
    ).toBeInTheDocument();
  });

  it('shows the history error separately from the gauge', async () => {
    // The two are separate requests, so one failing must not blank the other:
    // knowing the current value is useful even when the log will not load.
    vi.mocked(listConversationHistory).mockRejectedValue(new Error('history is down'));
    renderPanel();
    expect(await screen.findByTestId('conversation-chip')).toHaveTextContent('Spoke To Them');
    expect(
      await screen.findByText(/Could not load the conversation history\. history is down/),
    ).toBeInTheDocument();
  });
});
