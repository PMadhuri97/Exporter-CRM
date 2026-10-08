/**
 * Who is working on a company, on screen: the RM field and its served actions, the
 * stale-edit message with Reload, the reviewer line, the RM asked for when a check is
 * started, the nav badge and bulk reassignment. Nothing here decides a rule — each
 * test checks the screen offers what the server served and sends what it needs.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';
import { useHasPermission } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';

import {
  assignBackgroundCheckReview,
  assignRelationshipManager,
  getExporterProfileDetail,
  getWorklistCounts,
  listStaff,
  reassignRelationshipManagers,
  releaseBackgroundCheckReview,
  updateExporterProfile,
} from '../api';
import { CompanyPanel } from '../pages/panels/CompanyPanel';
import type { BackgroundCheck, ExporterProfileDetail, ExporterProfileListItem } from '../types';

import { BackgroundCheckMoveDialog } from './BackgroundCheckMoveDialog';
import { BulkReassignPanel } from './BulkReassignPanel';
import { RelationshipManagerField } from './RelationshipManagerField';
import { ReviewerLine } from './ReviewerLine';
import { WorklistBadge } from './WorklistBadge';

vi.mock('../api', () => ({
  assignRelationshipManager: vi.fn(),
  reassignRelationshipManagers: vi.fn(),
  listStaff: vi.fn(),
  updateExporterProfile: vi.fn(),
  getExporterProfileDetail: vi.fn(),
  getWorklistCounts: vi.fn(),
  claimBackgroundCheckReview: vi.fn(),
  assignBackgroundCheckReview: vi.fn(),
  releaseBackgroundCheckReview: vi.fn(),
}));
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useHasPermission: vi.fn(),
}));

const ME = 'me-0000';
const COMPANY = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function signInAs(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: ME,
    email: 'me@aner.example',
    full_name: 'Me',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- concise fixture
    role: role as any,
    is_active: true,
  } as ReturnType<typeof useCurrentUser>);
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function profile(overrides: Partial<ExporterProfileDetail> = {}): ExporterProfileDetail {
  return {
    customer_id: COMPANY,
    name: 'Acme Exports',
    country: 'IN',
    cin: null,
    gstins: [],
    pan: null,
    iec: null,
    source: 'SALES',
    relationship_manager: null,
    relationship_manager_user_id: null,
    relationship_manager_name: null,
    relationship_manager_inactive: false,
    relationship_manager_actions: [],
    journey: 'LEAD',
    qualification: 'NOT_YET_REVIEWED',
    marker: 'NONE',
    marker_reason: null,
    industry: 'Textiles',
    export_markets: null,
    products: null,
    year_established: null,
    registration_number: null,
    identity_type: null,
    pipeline_status: 'IN_PIPELINE',
    date_added: '2026-10-01T00:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
    contacts: [],
    recent_activities: [],
    gstin_warnings: [],
    allowed_marker_moves: [],
    ...overrides,
  } as ExporterProfileDetail;
}

const STAFF = {
  staff: [
    { id: 'rm-a', name: 'Asha Rao', role: 'OPERATIONS', companies: 3, open_reviews: 0 },
    { id: 'rm-b', name: 'Vikram Shah', role: 'OPERATIONS', companies: 1, open_reviews: 0 },
  ],
};

beforeEach(() => {
  vi.clearAllMocks();
  signInAs('OPERATIONS');
  vi.mocked(useHasPermission).mockReturnValue(false);
  vi.mocked(listStaff).mockResolvedValue(STAFF as never);
  vi.mocked(getExporterProfileDetail).mockResolvedValue(profile());
});

describe('the relationship manager field', () => {
  it('lets an RM claim a company with no RM, sending what the screen showed', async () => {
    vi.mocked(assignRelationshipManager).mockResolvedValue(profile());
    wrap(<RelationshipManagerField profile={profile({ relationship_manager_actions: ['CLAIM'] })} />);
    expect(screen.getByText('Unassigned')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Assign to me' }));
    await waitFor(() =>
      expect(assignRelationshipManager).toHaveBeenCalledWith(COMPANY, {
        user_id: ME,
        seen_user_id: null,
        reason: null,
      }),
    );
  });

  it('reads the name, and offers nothing it was not served', () => {
    wrap(
      <RelationshipManagerField
        profile={profile({
          relationship_manager_user_id: 'rm-a',
          relationship_manager_name: 'Asha Rao',
          relationship_manager_inactive: true,
        })}
      />,
    );
    expect(screen.getByText('Asha Rao')).toBeInTheDocument();
    expect(screen.getByText('Deactivated')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('asks a lead for a reason before changing an RM', async () => {
    vi.mocked(assignRelationshipManager).mockResolvedValue(profile());
    wrap(
      <RelationshipManagerField
        profile={profile({
          relationship_manager_user_id: 'rm-a',
          relationship_manager_name: 'Asha Rao',
          relationship_manager_actions: ['CHANGE', 'CLEAR'],
        })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Change' }));
    const dialog = screen.getByRole('dialog', { name: 'Change the relationship manager' });
    const picker = within(dialog).getByLabelText(/Relationship manager/);
    await within(dialog).findByRole('option', { name: /Vikram Shah/ });
    // The current RM is not offered as their own replacement.
    expect(within(dialog).queryByRole('option', { name: /Asha Rao/ })).not.toBeInTheDocument();
    fireEvent.change(picker, { target: { value: 'rm-b' } });
    const save = within(dialog).getByRole('button', { name: 'Save' });
    expect(save).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'territory' } });
    fireEvent.click(save);
    await waitFor(() =>
      expect(assignRelationshipManager).toHaveBeenCalledWith(COMPANY, {
        user_id: 'rm-b',
        seen_user_id: 'rm-a',
        reason: 'territory',
      }),
    );
  });

  it('reloads the company when someone changed the RM first, so a retry sends the new one', async () => {
    vi.mocked(assignRelationshipManager).mockRejectedValue(
      new ApiError(409, 'Someone changed the RM since', 'RELATIONSHIP_MANAGER_CHANGED', null, null),
    );
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const invalidate = vi.spyOn(client, 'invalidateQueries');
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <RelationshipManagerField
            profile={profile({ relationship_manager_actions: ['CLAIM'] })}
          />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Assign to me' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Someone changed the RM since');
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['exporterProfile', COMPANY] });
  });
});

describe('two people editing one company', () => {
  it('says who changed the field and when, keeps the typed value, and reloads', async () => {
    vi.mocked(updateExporterProfile).mockRejectedValue(
      new ApiError(409, 'industry was changed', 'COMPANY_FIELD_CHANGED', null, {
        field: 'industry',
        current: 'Leather',
        changed_by_name: 'Vikram Shah',
        changed_at: '2026-10-07T09:02:00Z',
      }),
    );
    wrap(<CompanyPanel profile={profile()} canEdit />);
    fireEvent.click(screen.getByRole('button', { name: 'Edit Industry' }));
    const input = screen.getByRole('textbox', { name: 'Industry' });
    fireEvent.change(input, { target: { value: 'Spices' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(await screen.findByRole('alert')).toHaveTextContent(
      /Changed by Vikram Shah at .* to Leather\. Reload before saving\./,
    );
    expect(updateExporterProfile).toHaveBeenCalledWith(COMPANY, {
      industry: 'Spices',
      seen: { industry: 'Textiles' },
    });
    expect(input).toHaveValue('Spices');
    const before = vi.mocked(getExporterProfileDetail).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }));
    await waitFor(() =>
      expect(vi.mocked(getExporterProfileDetail).mock.calls.length).toBeGreaterThan(before),
    );
    expect(screen.getByRole('textbox', { name: 'Industry' })).toHaveValue('Spices');
  });
});

function standing(overrides: Partial<BackgroundCheck> = {}): BackgroundCheck {
  return {
    company_id: COMPANY,
    value: 'IN_REVIEW',
    risk_rating: null,
    allowed_moves: [],
    clear_blocked_reasons: [],
    reviewer_id: null,
    reviewer_name: null,
    reviewer_assigned_at: null,
    reviewer_inactive: false,
    review_actions: [],
    relationship_manager_required: false,
    ...overrides,
  } as BackgroundCheck;
}

describe('the reviewer line', () => {
  it('says who holds the review, and offers only the served actions', () => {
    wrap(
      <ReviewerLine
        customerId={COMPANY}
        standing={standing({
          reviewer_id: 'r1',
          reviewer_name: 'Meera Iyer',
          reviewer_assigned_at: '2026-10-07T09:00:00Z',
          review_actions: ['RELEASE'],
        })}
      />,
    );
    expect(screen.getByText('Meera Iyer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Release' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Assign/ })).not.toBeInTheDocument();
  });

  it('releases with an optional note', async () => {
    vi.mocked(releaseBackgroundCheckReview).mockResolvedValue(standing());
    wrap(
      <ReviewerLine
        customerId={COMPANY}
        standing={standing({ reviewer_id: 'r1', reviewer_name: 'Meera', review_actions: ['RELEASE'] })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Release' }));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Release' }));
    await waitFor(() => expect(releaseBackgroundCheckReview).toHaveBeenCalledWith(COMPANY, null));
  });

  it('needs a reason to take a review from someone', async () => {
    vi.mocked(listStaff).mockResolvedValue({
      staff: [{ id: 'c2', name: 'Kiran', role: 'COMPLIANCE', companies: 0, open_reviews: 4 }],
    } as never);
    vi.mocked(assignBackgroundCheckReview).mockResolvedValue(standing());
    wrap(
      <ReviewerLine
        customerId={COMPANY}
        standing={standing({ reviewer_id: 'r1', reviewer_name: 'Meera', review_actions: ['RELEASE', 'ASSIGN'] })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Reassign' }));
    const dialog = screen.getByRole('dialog', { name: 'Assign the review' });
    await within(dialog).findByRole('option', { name: 'Kiran (4 open)' });
    fireEvent.change(within(dialog).getByLabelText(/Reviewer/), { target: { value: 'c2' } });
    expect(within(dialog).getByRole('button', { name: 'Assign' })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/Reason/), { target: { value: 'balance' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Assign' }));
    await waitFor(() =>
      expect(assignBackgroundCheckReview).toHaveBeenCalledWith(COMPANY, {
        user_id: 'c2',
        reason: 'balance',
      }),
    );
  });

  it('is not shown once the check is decided', () => {
    wrap(<ReviewerLine customerId={COMPANY} standing={standing({ value: 'CLEAR' })} />);
    expect(screen.queryByTestId('reviewer-line')).not.toBeInTheDocument();
  });
});

const START = [
  { to_value: 'IN_REVIEW', reason_required: false, risk_required: false, approval_required: false },
] as BackgroundCheck['allowed_moves'];

describe('starting a check on a company with no RM', () => {
  it('makes an RM the RM in the same request', () => {
    const submit = vi.fn();
    wrap(
      <BackgroundCheckMoveDialog
        moves={START}
        blockedReasons={[]}
        isPending={false}
        error={null}
        onSubmit={submit}
        onCancel={() => undefined}
        initialMove="IN_REVIEW"
        relationshipManagerRequired
      />,
    );
    expect(screen.getByText(/you will become its RM/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(submit).toHaveBeenCalledWith({
      to_value: 'IN_REVIEW',
      reason: null,
      risk_rating: null,
      relationship_manager_user_id: ME,
    });
  });

  it('holds the start for someone who cannot name an RM, and says why', () => {
    signInAs('COMPLIANCE');
    wrap(
      <BackgroundCheckMoveDialog
        moves={START}
        blockedReasons={[]}
        isPending={false}
        error={null}
        onSubmit={vi.fn()}
        onCancel={() => undefined}
        initialMove="IN_REVIEW"
        relationshipManagerRequired
      />,
    );
    expect(screen.getByRole('note')).toHaveTextContent('has no relationship manager');
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeDisabled();
  });

  it('lets a sales lead pick any RM', async () => {
    vi.mocked(useHasPermission).mockReturnValue(true);
    const submit = vi.fn();
    wrap(
      <BackgroundCheckMoveDialog
        moves={START}
        blockedReasons={[]}
        isPending={false}
        error={null}
        onSubmit={submit}
        onCancel={() => undefined}
        initialMove="IN_REVIEW"
        relationshipManagerRequired
      />,
    );
    await screen.findByRole('option', { name: 'Vikram Shah' });
    fireEvent.change(screen.getByLabelText(/Relationship manager/), { target: { value: 'rm-b' } });
    fireEvent.click(screen.getByRole('button', { name: 'Record decision' }));
    expect(submit).toHaveBeenCalledWith(expect.objectContaining({ relationship_manager_user_id: 'rm-b' }));
  });
});

describe('the navigation badge', () => {
  it('counts my reviews and what awaits my signature, and is red when work is overdue', async () => {
    signInAs('COMPLIANCE');
    vi.mocked(getWorklistCounts).mockResolvedValue({
      awaiting_review: 4,
      my_reviews: 2,
      awaiting_approval: 1,
      info_requested: 0,
      overdue: 1,
      needs_attention: 0,
    });
    wrap(<WorklistBadge kind="compliance" />);
    const badge = await screen.findByTestId('nav-badge-compliance');
    expect(badge).toHaveTextContent('3');
    expect(badge).toHaveAttribute('aria-label', expect.stringContaining('1 overdue'));
  });

  it('shows nothing for a role that may not read compliance work', () => {
    signInAs('DEVELOPER');
    wrap(<WorklistBadge kind="compliance" />);
    expect(getWorklistCounts).not.toHaveBeenCalled();
  });
});

describe('bulk reassignment', () => {
  const rows = [
    { customer_id: 'c1', relationship_manager_user_id: 'gone', relationship_manager_name: 'Left Already', relationship_manager_inactive: true },
  ] as ExporterProfileListItem[];

  it('checks first, then moves the companies a deactivated RM held', async () => {
    vi.mocked(reassignRelationshipManagers)
      .mockResolvedValueOnce({ bulk_run_id: null, dry_run: true, matched: 4, moved: 0, skipped: 0, company_ids: [], skipped_company_ids: [] })
      .mockResolvedValueOnce({ bulk_run_id: 'run', dry_run: false, matched: 4, moved: 4, skipped: 0, company_ids: [], skipped_company_ids: [] });
    const close = vi.fn();
    wrap(<BulkReassignPanel shown={rows} journey={undefined} onClose={close} />);
    await screen.findByRole('option', { name: 'Left Already (deactivated)' });
    fireEvent.change(screen.getByLabelText(/From/), { target: { value: 'gone' } });
    fireEvent.change(screen.getByLabelText(/^To/), { target: { value: 'rm-b' } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'left the company' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(await screen.findByRole('status')).toHaveTextContent('4 companies would move.');
    expect(reassignRelationshipManagers).toHaveBeenLastCalledWith({
      from_user_id: 'gone',
      to_user_id: 'rm-b',
      company_ids: null,
      journey: null,
      reason: 'left the company',
      dry_run: true,
    });
    fireEvent.click(screen.getByRole('button', { name: 'Reassign 4' }));
    await waitFor(() => expect(close).toHaveBeenCalled());
    expect(reassignRelationshipManagers).toHaveBeenLastCalledWith(
      expect.objectContaining({ dry_run: false }),
    );
  });

  it("says the list's lens applies to all of their companies", async () => {
    vi.mocked(reassignRelationshipManagers).mockResolvedValueOnce({ bulk_run_id: null, dry_run: true, matched: 2, moved: 0, skipped: 0, company_ids: [], skipped_company_ids: [] });
    wrap(<BulkReassignPanel shown={rows} journey="PROSPECT" onClose={vi.fn()} />);
    expect(screen.getByText('Moves all of their prospects, including those not on this page.')).toBeInTheDocument();
    await screen.findByRole('option', { name: 'Left Already (deactivated)' });
    fireEvent.change(screen.getByLabelText(/From/), { target: { value: 'gone' } });
    fireEvent.change(screen.getByLabelText(/^To/), { target: { value: 'rm-b' } });
    fireEvent.change(screen.getByLabelText(/Reason/), { target: { value: 'split the book' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check' }));
    expect(await screen.findByRole('status')).toHaveTextContent('2 companies would move (prospects only).');
    expect(reassignRelationshipManagers).toHaveBeenLastCalledWith(
      expect.objectContaining({ company_ids: null, journey: 'PROSPECT' }),
    );
    fireEvent.click(screen.getByRole('checkbox'));
    expect(screen.getByText('Moves only the companies listed below.')).toBeInTheDocument();
  });
});
