/**
 * The CRM's own parts (frontend-plan §6): each state they draw,
 * and above all what they never draw — the background-check badge for Developer, a
 * button for a move the server did not list, a download for a quarantined file, an
 * identifier lookup for a role that may not create.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { matchCompany } from '../../api';
import type { BackgroundCheckProposal, CrmDocument } from '../../types';

import { detectEntry } from './entry';
import { CheckStatus, ConversationPath, PartyCard, HandoverChecklist, DocumentsByCategory, IdentifierLookup, CompanyBadges } from './index';

vi.mock('../../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../api')>()),
  matchCompany: vi.fn(),
}));
vi.mock('../CompanyComplianceSummary', () => ({
  CompanyComplianceSummary: () => <p data-testid="compliance-summary">compliance</p>,
}));
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));

function as(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ id: '1', role } as unknown as ReturnType<typeof useCurrentUser>);
}

function wrap(ui: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  as('OPERATIONS');
});

describe('CompanyBadges', () => {
  const company = {
    journey: 'PROSPECT',
    qualification: 'QUALIFIED',
    conversation: 'INTERESTED',
    backgroundCheck: 'IN_REVIEW',
  } as const;

  it('draws the gauges side by side, never merged', () => {
    wrap(<CompanyBadges {...company} />);
    expect(screen.getByText('Prospect')).toBeInTheDocument();
    expect(screen.getByText('Qualified')).toBeInTheDocument();
    expect(screen.getByText('Interested')).toBeInTheDocument();
    expect(screen.getByText('In review')).toBeInTheDocument();
  });

  it('leaves the background check out for Developer — absent, not greyed', () => {
    as('DEVELOPER');
    wrap(<CompanyBadges {...company} size="card" />);
    expect(screen.getByText('Qualified')).toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('In review');
  });

  it('says awaiting approval and Re-KYC due in their own badges, beside the check', () => {
    wrap(<CompanyBadges {...company} backgroundCheck="CLEAR" awaitingApproval rekycDue size="card" />);
    expect(screen.getByText('Clear')).toBeInTheDocument();
    expect(screen.getByText('Awaiting approval')).toBeInTheDocument();
    expect(screen.getByText('Re-KYC due')).toBeInTheDocument();
  });

  it('draws status as words, never as a glyph alone', () => {
    const { container } = wrap(<CompanyBadges {...company} />);
    expect(container.querySelector('[data-lamp]')).toBeNull();
    for (const badge of container.querySelectorAll('[data-badge-tone]')) {
      expect(badge.textContent?.trim()).not.toBe('');
    }
  });

  it('says "Outside pipeline" for a buyer-only company and draws no gauges', () => {
    wrap(<CompanyBadges {...company} outsidePipeline />);
    expect(screen.getByText('Outside pipeline')).toBeInTheDocument();
    expect(screen.queryByText('Qualified')).not.toBeInTheDocument();
  });
});

describe('ConversationPath', () => {
  it('draws every step, but only the served moves are buttons', () => {
    wrap(
      <ConversationPath
        customerId="c1"
        value="SPOKE_TO_THEM"
        moves={[
          { to: 'INTERESTED', reason_required: false, check_back_required: false },
          { to: 'NOT_NOW', reason_required: true, check_back_required: true },
        ]}
      />,
    );
    const track = screen.getByTestId('conversation-path');
    expect(within(track).getAllByRole('button').map((b) => b.textContent)).toEqual(['Interested', 'Not now']);
    expect(within(track).getByText('Ready now')).toBeInTheDocument();
    expect(within(track).getByText('Spoke to them').closest('[aria-current]')).toHaveAttribute('aria-current', 'step');
  });

  it('has no buttons at all when the server lists no moves', () => {
    wrap(<ConversationPath customerId="c1" value="NOT_NOW" checkBackOn="2026-11-12" moves={[]} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText(/check back 12 Nov 2026/)).toBeInTheDocument();
  });

  it('offers Mark as current only once a served step is chosen', () => {
    wrap(
      <ConversationPath
        customerId="c1"
        value="SPOKE_TO_THEM"
        moves={[{ to: 'INTERESTED', reason_required: false, check_back_required: false }]}
      />,
    );
    expect(screen.queryByRole('button', { name: 'Mark as current' })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Interested' }));
    expect(screen.getByRole('button', { name: 'Interested' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'Mark as current' })).toBeInTheDocument();
  });
});

describe('CheckStatus', () => {
  it('offers only the allowed moves, and "Propose" where a second officer must approve', () => {
    const onChoose = vi.fn();
    wrap(
      <CheckStatus
        value="IN_REVIEW"
        moves={[
          { to_value: 'CLEAR', reason_required: true, risk_required: true, approval_required: true },
          { to_value: 'MORE_INFO', reason_required: true, risk_required: false, approval_required: false },
        ]}
        onChoose={onChoose}
      />,
    );
    const card = screen.getByTestId('check-status');
    expect(within(card).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'More information needed',
      'Propose Clear',
    ]);
    fireEvent.click(within(card).getByRole('button', { name: 'Propose Clear' }));
    expect(onChoose).toHaveBeenCalledWith('CLEAR');
  });

  it('draws an open proposal dashed, with the proposer signed and the approver waiting', () => {
    const proposal = {
      to_value: 'CLEAR',
      proposed_by: 'u1',
      proposed_by_name: 'R. Mehta',
      proposed_at: '2026-10-03T11:02:00Z',
    } as BackgroundCheckProposal;
    wrap(<CheckStatus value="IN_REVIEW" moves={[]} openProposal={proposal} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    const signatures = screen.getByTestId('proposal-signatures');
    expect(signatures).toHaveTextContent('Proposed by R. Mehta');
    expect(signatures).toHaveTextContent('Waiting for a second compliance officer');
  });
});

describe('HandoverChecklist', () => {
  it('shows the server’s sentence verbatim — never split into fake rows', () => {
    wrap(<HandoverChecklist blockedReason="the seller's background check is not clear; no pre-shipment document" />);
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent(
      "Not ready to hand over: the seller's background check is not clear; no pre-shipment document",
    );
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('draws nothing without a reason (Developer is sent none)', () => {
    const { container } = wrap(<HandoverChecklist blockedReason={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('becomes a checklist once structured conditions are served', () => {
    wrap(
      <HandoverChecklist
        blockedReason="x"
        conditions={[
          { key: 'customer', met: true, message: 'Seller is a customer' },
          { key: 'buyer_aml', met: false, message: "Buyer's AML is not passed", fixAt: { to: '/companies/b', label: 'Record on buyer' } },
        ]}
      />,
    );
    expect(screen.getByText('1 of 2 met')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Record on buyer' })).toHaveAttribute('href', '/companies/b');
  });
});

describe('DocumentsByCategory', () => {
  const file = (over: Partial<CrmDocument>): CrmDocument =>
    ({
      id: crypto.randomUUID(),
      company_id: 'c1',
      deal_id: null,
      category: 'KYC',
      document_type: 'pan_card',
      source: 'EXPORTER_UPLOAD',
      file_name: 'pan.pdf',
      content_type: 'application/pdf',
      size_bytes: 2048,
      uploaded_by: 'u1',
      uploaded_at: '2026-10-01T10:00:00Z',
      scan_status: 'AVAILABLE',
      scanner_name: 'pass-through',
      is_downloadable: true,
      ...over,
    }) as CrmDocument;

  it('groups by category, never offers a quarantined file, and labels the prototype scanner once', () => {
    wrap(
      <DocumentsByCategory
        isLoading={false}
        emptyMessage="None"
        documents={[
          file({ file_name: 'pan.pdf' }),
          file({ file_name: 'bad.pdf', scan_status: 'QUARANTINED', is_downloadable: false }),
          file({ category: 'PRE_SHIPMENT', file_name: 'invoice.pdf', scan_status: 'PENDING_SCAN', is_downloadable: false }),
        ]}
        required={[
          { category: 'KYC', label: 'KYC' },
          { category: 'PRE_SHIPMENT', label: 'Pre-shipment' },
          { category: 'INSURANCE', label: 'Insurance' },
        ]}
      />,
    );
    expect(screen.getByRole('group', { name: 'KYC' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Download pan.pdf' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download bad.pdf' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Download invoice.pdf' })).not.toBeInTheDocument();
    expect(screen.getAllByText(/pass-through scanner/)).toHaveLength(1);
    // Present means served: an AVAILABLE file. One still waiting on the scan is missing.
    expect(screen.getByTestId('required-category-KYC')).toHaveTextContent('present');
    expect(screen.getByTestId('required-category-PRE_SHIPMENT')).toHaveTextContent('missing');
    expect(screen.getByTestId('required-category-INSURANCE')).toHaveTextContent('missing');
    // No upload for a role the page gave none.
    expect(screen.queryByRole('button', { name: 'Upload a document' })).not.toBeInTheDocument();
  });
});

describe('IdentifierLookup', () => {
  it.each([
    ['AAAPL1234C', 'PAN'],
    ['27AAAPL1234C1ZV', 'GSTIN'],
    ['0123456789', 'IEC'],
    ['U74999MH2009PTC123456', 'CIN'],
    ['Lakshmi Polymers', 'name'],
  ])('reads %s as %s', (text, kind) => {
    expect(detectEntry(text).kind).toBe(kind);
  });

  it('takes the PAN from a GSTIN and asks the server once name and country are known', async () => {
    vi.mocked(matchCompany).mockResolvedValue({
      kind: 'MATCHED',
      company_id: 'c9',
      candidates: [{ company_id: 'c9', name: 'Bharat Precision Metals', country: 'IN', pipeline_status: 'IN_PIPELINE' }],
    } as never);
    wrap(<IdentifierLookup value="27AAAPL1234C1ZV" onChange={vi.fn()} name="Bharat Precision" country="IN" />);
    expect(screen.getByTestId('entry-kind')).toHaveTextContent('GSTIN');
    expect(screen.getByText('AAAPL1234C')).toBeInTheDocument();
    await waitFor(() =>
      expect(matchCompany).toHaveBeenCalledWith(
        { name: 'Bharat Precision', country: 'IN', gstin: '27AAAPL1234C1ZV' },
        expect.anything(),
      ),
    );
    expect(await screen.findByText('Bharat Precision Metals')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute('href', '/companies/c9');
  });

  it('never asks when live matching is off', async () => {
    wrap(<IdentifierLookup value="Lakshmi Polymers" onChange={vi.fn()} country="IN" live={false} />);
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(matchCompany).not.toHaveBeenCalled();
  });
});

describe('PartyCard', () => {
  it('names the party, links to its record, and shows compliance to staff only', () => {
    const { unmount } = wrap(<PartyCard role="Buyer" companyId="b1" name="Rotterdam Trading BV" country="NL" outsidePipeline />);
    const card = screen.getByRole('group', { name: 'Buyer: Rotterdam Trading BV' });
    expect(within(card).getByRole('link', { name: 'Rotterdam Trading BV' })).toHaveAttribute('href', '/companies/b1');
    expect(within(card).getByText('Outside pipeline')).toBeInTheDocument();
    expect(within(card).getByTestId('compliance-summary')).toBeInTheDocument();
    unmount();

    as('DEVELOPER');
    wrap(<PartyCard role="Seller" companyId="s1" name="Bharat" />);
    expect(screen.queryByTestId('compliance-summary')).not.toBeInTheDocument();
  });
});
