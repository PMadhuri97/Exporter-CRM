import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getQualification, getScreeningReview, listCompanyHistory, listDealHistory } from '../api';
import type { HistoryEntry, Qualification, ScreeningReviewList } from '../types';

import { CompanyHistory, DealHistory } from './HistoryTimeline';

vi.mock('../api', () => ({
  listCompanyHistory: vi.fn(),
  listDealHistory: vi.fn(),
  getScreeningReview: vi.fn(),
  getQualification: vi.fn(),
}));

const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const DEAL_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const ACTOR_ID = 'cc56991e-0000-4000-8000-000000000001';

function entry(overrides: Partial<HistoryEntry>): HistoryEntry {
  return {
    id: crypto.randomUUID(),
    company_id: COMPANY_ID,
    deal_id: null,
    dimension: 'journey',
    event_type: 'lifecycle_transition',
    from_value: null,
    to_value: 'LEAD',
    actor_id: ACTOR_ID,
    actor_name: 'Priya Ops',
    reason: null,
    source: 'test',
    details: null,
    occurred_at: '2026-09-28T17:36:18Z',
    ...overrides,
  };
}

function page(entries: HistoryEntry[]) {
  return { entries, total: entries.length, limit: 25, offset: 0 };
}

function renderWith(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

async function rows() {
  return screen.findAllByTestId('history-row');
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getScreeningReview).mockResolvedValue({
    customer_id: COMPANY_ID,
    items: [],
    catalogue: [
      {
        key: 'exception-approval',
        label: 'If an exception exists, has it been formally approved?',
        section: 'Approvals',
      },
    ],
    capabilities: { can_record_decision: false },
  } as ScreeningReviewList);
  vi.mocked(getQualification).mockResolvedValue({
    standings: [{ criterion: { key: 'revenue', label: 'Annual revenue' } }],
  } as unknown as Qualification);
});

describe('a deal buyer change', () => {
  it('says the buyer was recorded, not "Open → Open"', async () => {
    vi.mocked(listDealHistory).mockResolvedValue(
      page([
        entry({
          deal_id: DEAL_ID,
          dimension: 'deal',
          event_type: 'deal_buyer_changed',
          from_value: 'OPEN',
          to_value: 'OPEN',
          details: { buyer_name: 'Rotterdam Living BV', changed: ['country', 'name'], created: true },
        }),
      ]),
    );
    renderWith(<DealHistory dealId={DEAL_ID} />);
    const [row] = await rows();
    expect(row).toHaveTextContent('Buyer recorded: Rotterdam Living BV');
    expect(row).not.toHaveTextContent('Open → Open');
  });

  it('names the fields an update changed', async () => {
    vi.mocked(listDealHistory).mockResolvedValue(
      page([
        entry({
          deal_id: DEAL_ID,
          dimension: 'deal',
          event_type: 'deal_buyer_changed',
          from_value: 'GATHERING_PAPERWORK',
          to_value: 'GATHERING_PAPERWORK',
          details: {
            buyer_name: 'Rotterdam Living BV',
            changed: ['contact_email', 'tax_id'],
            created: false,
          },
        }),
      ]),
    );
    renderWith(<DealHistory dealId={DEAL_ID} />);
    const [row] = await rows();
    expect(row).toHaveTextContent('Buyer updated: contact email, tax ID (Rotterdam Living BV)');
  });
});

describe('rows about one thing of several', () => {
  it('names the screening item, the criterion and the check', async () => {
    vi.mocked(listCompanyHistory).mockResolvedValue(
      page([
        entry({
          dimension: 'screening',
          event_type: 'screening_initial',
          to_value: 'PASSED',
          details: { item_key: 'exception-approval' },
        }),
        entry({
          dimension: 'qualification',
          event_type: 'qualification_result',
          to_value: 'PASS',
          details: { criterion_key: 'revenue' },
        }),
        entry({
          dimension: 'verification',
          event_type: 'verification_initial',
          to_value: 'FAILED',
          details: { verification_type: 'SANCTIONS', entity_type: 'BUYER' },
        }),
        entry({
          dimension: 'verification',
          event_type: 'verification_reviewed',
          to_value: 'ACCEPTED',
          details: { verification_type: 'KYB' },
        }),
      ]),
    );
    renderWith(<CompanyHistory customerId={COMPANY_ID} />);
    const [screening, criterion, check, review] = await rows();
    expect(await within(screening!).findByText(/formally approved\?/)).toBeInTheDocument();
    // A question keeps its question mark, with no colon after it.
    expect(screening).toHaveTextContent('If an exception exists, has it been formally approved? Passed');
    expect(await within(criterion!).findByText(/Annual revenue:/)).toBeInTheDocument();
    expect(criterion).toHaveTextContent('Annual revenue: Pass');
    expect(check).toHaveTextContent('Buyer sanctions check: Failed');
    expect(review).toHaveTextContent('KYB check reviewed: Accepted');
  });
});

describe('background-check approvals and cycles (Developer 1)', () => {
  it('names the proposed move and the cycle kind', async () => {
    vi.mocked(listCompanyHistory).mockResolvedValue(
      page([
        entry({
          dimension: 'background_check_approval',
          event_type: 'background_check_proposed',
          from_value: null,
          to_value: 'OPEN',
          details: { proposal_id: 'p1', from_value: 'IN_REVIEW', to_value: 'CLEAR' },
        }),
        entry({
          dimension: 'background_check_approval',
          event_type: 'background_check_rejected',
          from_value: 'OPEN',
          to_value: 'REJECTED',
          reason: 'AML needs a second look',
          details: { proposal_id: 'p1', from_value: 'IN_REVIEW', to_value: 'CLEAR' },
        }),
        entry({
          dimension: 'check_cycle',
          event_type: 'check_cycle_started',
          from_value: '1',
          to_value: '2',
          details: { kind: 'RE_KYC' },
        }),
      ]),
    );
    renderWith(<CompanyHistory customerId={COMPANY_ID} />);
    const [proposed, rejected, cycle] = await rows();
    expect(proposed).toHaveTextContent('Clear proposal: Open');
    expect(rejected).toHaveTextContent('Clear proposal: Open → Rejected');
    expect(rejected).toHaveTextContent('AML needs a second look');
    expect(cycle).toHaveTextContent('Re-KYC — check cycle: 1 → 2');
  });
});

describe('who acted', () => {
  it('shows the name the server resolved, the platform, or a shortened id', async () => {
    vi.mocked(listCompanyHistory).mockResolvedValue(
      page([
        entry({ to_value: 'LEAD' }),
        entry({ to_value: 'PROSPECT', actor_id: null, actor_name: null }),
        entry({ to_value: 'CUSTOMER', actor_name: null }),
      ]),
    );
    renderWith(<CompanyHistory customerId={COMPANY_ID} />);
    const [named, platform, unnamed] = await rows();
    expect(named).toHaveTextContent('By Priya Ops');
    expect(platform).toHaveTextContent('By the platform');
    expect(unnamed).toHaveTextContent('By User cc56991e…');
    expect(unnamed).not.toHaveTextContent(ACTOR_ID);
  });
});
