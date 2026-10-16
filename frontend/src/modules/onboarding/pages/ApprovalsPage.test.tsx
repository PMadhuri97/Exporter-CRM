/**
 * Compliance work: the rail lists the worklists the server
 * computes — reviews awaiting a reviewer, this officer's reviews, what awaits their
 * signature, what is due for Re-KYC, and, for a compliance lead, everyone's reviews,
 * the overdue and what needs attention. Choosing a case opens that company's
 * background check beside the rail; a review nobody holds offers *Assign to me*.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useHasPermission } from '@/platform/access';
import { ShellProvider } from '@/platform/shell';

import {
  listComplianceWork,
  listOpenProposals,
  listProposalsIReviewed,
  listReKycDue,
} from '../api';
import type { BackgroundCheckProposal, ComplianceWorkItem, ComplianceWorkView } from '../types';

import { ApprovalsPage } from './ApprovalsPage';

vi.mock('../api', () => ({
  listOpenProposals: vi.fn(),
  listProposalsIReviewed: vi.fn(),
  listReKycDue: vi.fn(),
  listComplianceWork: vi.fn(),
  claimBackgroundCheckReview: vi.fn(),
  assignBackgroundCheckReview: vi.fn(),
  releaseBackgroundCheckReview: vi.fn(),
  approveBackgroundCheckProposal: vi.fn(),
  rejectBackgroundCheckProposal: vi.fn(),
  withdrawBackgroundCheckProposal: vi.fn(),
}));
vi.mock('./panels/BackgroundCheckPanel', () => ({
  BackgroundCheckPanel: ({ customerId }: { customerId: string }) => (
    <p data-testid="case-panel">{customerId}</p>
  ),
}));
vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useHasPermission: vi.fn(),
}));
// The page reads the signed-in id to say which half of maker-checker this officer was.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(() => ({ id: 'me', email: 'me@aner.example', role: 'COMPLIANCE' })),
}));

const PROPOSAL = {
  id: 'p1',
  company_id: 'company-a',
  company_name: 'Bharat Precision Metals',
  to_value: 'CLEAR',
  risk_rating: 'LOW',
  reason: 'Every check passed.',
  proposed_by: 'maker',
  proposed_by_name: 'R. Mehta',
  proposed_at: '2026-10-03T11:02:00Z',
  allowed_actions: ['APPROVE', 'REJECT'],
  needs_senior_approval: false,
  is_due_soon: false,
  is_overdue: false,
} as BackgroundCheckProposal;

function item(overrides: Partial<ComplianceWorkItem>): ComplianceWorkItem {
  return {
    company_id: 'company-x',
    company_name: 'Unnamed',
    journey: 'PROSPECT',
    pipeline_status: 'IN_PIPELINE',
    background_check: 'IN_REVIEW',
    stage: 'review',
    relationship_manager_id: null,
    relationship_manager_name: null,
    relationship_manager_inactive: false,
    reviewer_id: null,
    reviewer_name: null,
    reviewer_inactive: false,
    waiting_since: '2026-10-05T09:00:00Z',
    due_at: null,
    is_due_soon: false,
    is_overdue: false,
    rejection_count: 0,
    needs_attention: false,
    needs_senior_approval: false,
    ...overrides,
  } as ComplianceWorkItem;
}

const INITIAL_WORK: Record<ComplianceWorkView, ComplianceWorkItem[]> = {
  awaiting: [item({ company_id: 'company-c', company_name: 'Deccan Leather' })],
  mine: [
    item({
      company_id: 'company-d',
      company_name: 'Eastern Spice',
      reviewer_id: 'me',
      reviewer_name: 'Me',
      due_at: '2026-10-06T09:00:00Z',
      is_overdue: true,
      rejection_count: 2,
    }),
  ],
  in_review: [item({ company_id: 'company-e', company_name: 'Fortune Textiles', reviewer_name: 'Priya' })],
  overdue: [],
  needs_attention: [],
};

let client: QueryClient;

function renderPage(at = '/review') {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[at]}>
        <ShellProvider>
          <ApprovalsPage />
        </ShellProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

let WORK: Record<ComplianceWorkView, ComplianceWorkItem[]>;

beforeEach(() => {
  vi.clearAllMocks();
  WORK = { ...INITIAL_WORK };
  vi.mocked(useHasPermission).mockReturnValue(false);
  vi.mocked(listComplianceWork).mockImplementation(async (view) => ({
    view,
    items: WORK[view],
    total: WORK[view].length,
  }));
  vi.mocked(listOpenProposals).mockResolvedValue({ proposals: [PROPOSAL], total: 1, limit: 50, offset: 0 } as never);
  vi.mocked(listProposalsIReviewed).mockResolvedValue({
    proposals: [],
    total: 0,
    limit: 50,
    offset: 0,
  } as never);
  vi.mocked(listReKycDue).mockResolvedValue({
    companies: [
      {
        company_id: 'company-b',
        company_name: 'Coastal Seafood',
        journey: 'CUSTOMER',
        background_check: 'CLEAR',
        expires_at: '2026-10-12',
        is_expired: false,
        current_cycle_number: 1,
        pipeline_status: 'IN_PIPELINE',
      },
    ],
    total: 1,
    limit: 50,
    offset: 0,
    before: '2026-11-04',
  } as never);
});

describe('Compliance work', () => {
  it('shows one list at a time, with each tab’s count, and opens the first case', async () => {
    renderPage();
    expect(await screen.findByRole('radio', { name: /Awaiting review/ })).toBeChecked();
    const list = await screen.findByRole('navigation', { name: 'Awaiting review' });
    expect(await within(list).findByText('Deccan Leather')).toBeInTheDocument();
    // The other lists are not stacked under it.
    expect(within(list).queryByText('Eastern Spice')).not.toBeInTheDocument();
    expect(within(list).queryByText('Bharat Precision Metals')).not.toBeInTheDocument();
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-c');
  });

  it('says how long, whether it is late and how often it came back', async () => {
    renderPage('/review?tab=mine');
    const list = await screen.findByRole('navigation', { name: 'My reviews' });
    expect(await within(list).findByText('Overdue')).toBeInTheDocument();
    expect(within(list).getByText('Returned ×2')).toBeInTheDocument();
    expect(within(list).getByText(/In review · waited/)).toBeInTheDocument();
  });

  it('lists what awaits a signature and what is due on their own tabs', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('radio', { name: /To approve/ }));
    const approve = await screen.findByRole('navigation', { name: 'To approve' });
    expect(await within(approve).findByText('Bharat Precision Metals')).toBeInTheDocument();
    expect(listOpenProposals).toHaveBeenCalledWith({ awaitingMe: true, limit: 50 });
    fireEvent.click(screen.getByRole('radio', { name: /Re-KYC due/ }));
    const due = await screen.findByRole('navigation', { name: 'Re-KYC due' });
    fireEvent.click(await within(due).findByRole('button', { name: /Coastal Seafood/ }));
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-b');
  });

  it('follows a company to My reviews when its review is taken, instead of jumping to the top', async () => {
    renderPage('/review?tab=awaiting&company=company-c');
    expect(await screen.findByTestId('case-panel')).toHaveTextContent('company-c');
    // Someone (the reviewer line in the case) takes the review: the next read moves it.
    WORK.mine = [...WORK.mine, item({ company_id: 'company-c', company_name: 'Deccan Leather', reviewer_id: 'me' })];
    WORK.awaiting = [];
    await act(() => client.invalidateQueries());
    const list = await screen.findByRole('navigation', { name: 'My reviews' });
    expect(within(list).getByText('Deccan Leather')).toBeInTheDocument();
    expect(screen.getByTestId('case-panel')).toHaveTextContent('company-c');
  });

  it('keeps everyone’s reviews, the overdue and what needs attention from a non-lead', async () => {
    renderPage();
    await screen.findByRole('navigation', { name: 'Awaiting review' });
    expect(screen.queryByRole('radio', { name: 'Team' })).not.toBeInTheDocument();
    expect(listComplianceWork).not.toHaveBeenCalledWith('in_review');
  });

  it('gives a compliance lead the Team tab, filtered within it', async () => {
    vi.mocked(useHasPermission).mockReturnValue(true);
    WORK.needs_attention = [item({ company_id: 'company-f', company_name: 'Goa Cashew' })];
    renderPage();
    fireEvent.click(await screen.findByRole('radio', { name: 'Team' }));
    const team = await screen.findByRole('navigation', { name: 'Team' });
    expect(await within(team).findByText('Goa Cashew')).toBeInTheDocument();
    fireEvent.click(within(team).getByRole('radio', { name: 'Everyone’s reviews' }));
    expect(await within(team).findByText('Fortune Textiles')).toBeInTheDocument();
  });
});

describe('Compliance work — Reviewed', () => {
  /** A proposal as the reviewed listing returns it. */
  const reviewed = (overrides: Record<string, unknown>) =>
    ({
      id: 'r1',
      company_id: 'company-r',
      company_name: 'Reviewed Co',
      to_value: 'CLEAR',
      risk_rating: null,
      status: 'OPEN',
      proposed_by: 'me',
      proposed_by_name: 'Me',
      proposed_at: '2026-10-01T09:00:00Z',
      resolved_by: null,
      resolved_by_name: null,
      resolved_at: null,
      ...overrides,
    }) as unknown as BackgroundCheckProposal;

  const open = async (rows: BackgroundCheckProposal[]) => {
    vi.mocked(listProposalsIReviewed).mockResolvedValue({
      proposals: rows,
      total: rows.length,
      limit: 50,
      offset: 0,
    } as never);
    renderPage('/review?tab=reviewed');
    // The name appears on the row and again as the chosen company's heading.
    return screen.findAllByText('Reviewed Co');
  };

  it('says what became of a proposal this officer made', async () => {
    await open([
      reviewed({
        status: 'APPROVED',
        resolved_by: 'checker',
        resolved_by_name: 'A Checker',
        resolved_at: '2026-10-02T09:00:00Z',
      }),
    ]);

    expect(screen.getByText(/You proposed/)).toBeInTheDocument();
    expect(screen.getByText(/approved by A Checker/)).toBeInTheDocument();
  });

  it('marks one still waiting rather than leaving it out', async () => {
    // The proposal an officer is waiting on is the one they look for.
    await open([reviewed({ status: 'OPEN' })]);

    expect(screen.getByText(/awaiting approval/)).toBeInTheDocument();
  });

  it('says what this officer did to somebody else’s proposal', async () => {
    await open([
      reviewed({
        proposed_by: 'someone-else',
        proposed_by_name: 'A Maker',
        status: 'REJECTED',
        resolved_by: 'me',
        resolved_by_name: 'Me',
        resolved_at: '2026-10-03T09:00:00Z',
      }),
    ]);

    expect(screen.getByText(/You rejected/)).toBeInTheDocument();
    expect(screen.getByText(/proposed by A Maker/)).toBeInTheDocument();
  });

  it('carries no count, since a record only ever grows', async () => {
    await open([reviewed({})]);

    // `Segmented` renders its options as radios, as the other tab tests read them.
    const tab = screen.getByRole('radio', { name: /Reviewed/ });
    expect(tab.textContent?.replace('Reviewed', '').trim()).toBe('');
  });

  it('says so plainly when the period holds nothing', async () => {
    vi.mocked(listProposalsIReviewed).mockResolvedValue({
      proposals: [],
      total: 0,
      limit: 50,
      offset: 0,
    } as never);
    renderPage('/review?tab=reviewed');

    expect(
      await screen.findByText(/have not proposed or decided anything/),
    ).toBeInTheDocument();
  });
});
