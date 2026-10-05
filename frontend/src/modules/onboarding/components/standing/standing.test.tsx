/**
 * The signature components (frontend-plan §6): each state they draw,
 * and above all what they never draw — the background-check lamp for Developer, a
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
import { CheckRunway, GaugeTrack, Lamp, PartyCard, Preflight, Shelf, SmartEntry, Standing } from './index';

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

/** The track's labels, left to right, as the test's layout lays them out. */
const CONVERSATION_ORDER = ['Not contacted', 'Reaching out', 'Spoke to them', 'Interested', 'Ready now'];

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

describe('Lamp', () => {
  it('is decorative beside words, and an image with a name when it stands alone', () => {
    const { container, rerender } = render(<Lamp shape="full" meaning="positive" />);
    expect(container.firstElementChild).toHaveAttribute('aria-hidden', 'true');
    rerender(<Lamp shape="triangle" meaning="negative" label="Flagged" awaitingApproval attentionDot />);
    const lamp = screen.getByRole('img', { name: 'Flagged' });
    expect(lamp).toHaveAttribute('data-lamp', 'triangle');
    expect(lamp.querySelector('[data-overlay="awaiting-approval"]')).not.toBeNull();
    expect(lamp.querySelector('[data-overlay="rekyc-due"]')).not.toBeNull();
  });
});

describe('Standing', () => {
  const company = {
    journey: 'PROSPECT',
    qualification: 'QUALIFIED',
    conversation: 'INTERESTED',
    backgroundCheck: 'IN_REVIEW',
  } as const;

  it('draws the gauges side by side, never merged', () => {
    wrap(<Standing {...company} />);
    expect(screen.getByText('Prospect')).toBeInTheDocument();
    expect(screen.getByText('Qualified')).toBeInTheDocument();
    expect(screen.getByText('Interested')).toBeInTheDocument();
    expect(screen.getByText('In review')).toBeInTheDocument();
  });

  it('leaves the background check out for Developer — absent, not greyed', () => {
    as('DEVELOPER');
    wrap(<Standing {...company} size="card" />);
    expect(screen.getByRole('img', { name: 'Qualification: Qualified' })).toBeInTheDocument();
    expect(screen.queryByRole('img', { name: /Background check/ })).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent('In review');
  });

  it('marks awaiting approval and Re-KYC due on the check lamp', () => {
    wrap(<Standing {...company} backgroundCheck="CLEAR" awaitingApproval rekycDue size="card" />);
    expect(
      screen.getByRole('img', { name: 'Background check: Clear, awaiting approval, Re-KYC due' }),
    ).toBeInTheDocument();
  });

  it('says "Outside pipeline" for a buyer-only company and draws no gauges', () => {
    wrap(<Standing {...company} outsidePipeline />);
    expect(screen.getByText('Outside pipeline')).toBeInTheDocument();
    expect(screen.queryByText('Qualified')).not.toBeInTheDocument();
  });

  it('opens a chapter from a hero segment', () => {
    const onOpen = vi.fn();
    wrap(<Standing {...company} size="hero" onOpen={onOpen} details={{ qualification: '12 Sep' }} />);
    fireEvent.click(screen.getByRole('button', { name: /Qualification/ }));
    expect(onOpen).toHaveBeenCalledWith('qualification');
    expect(screen.getByText('12 Sep')).toBeInTheDocument();
  });
});

describe('GaugeTrack', () => {
  it('draws every node, but only the served moves are buttons', () => {
    wrap(
      <GaugeTrack
        customerId="c1"
        value="SPOKE_TO_THEM"
        moves={[
          { to: 'INTERESTED', reason_required: false, check_back_required: false },
          { to: 'NOT_NOW', reason_required: true, check_back_required: true },
        ]}
      />,
    );
    const track = screen.getByTestId('gauge-track');
    expect(within(track).getAllByRole('button').map((b) => b.textContent)).toEqual(['Interested', 'Not now']);
    expect(within(track).getByText('Ready now')).toBeInTheDocument();
    expect(within(track).getByText('Spoke to them').closest('[aria-current]')).toHaveAttribute('aria-current', 'step');
  });

  it('has no buttons at all when the server lists no moves', () => {
    wrap(<GaugeTrack customerId="c1" value="NOT_NOW" checkBackOn="2026-11-12" moves={[]} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText(/check back 12 Nov 2026/)).toBeInTheDocument();
  });

  it('moves one ring to the node the server now reports, instead of redrawing two', () => {
    // jsdom has no layout: give every element a box so the ring can be measured.
    const boxes = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const current = this.getAttribute('aria-current') === 'step';
      const at = current ? CONVERSATION_ORDER.indexOf(this.textContent ?? '') * 120 : 0;
      return { left: at, top: 0, width: current ? 110 : 600, height: 28, right: 0, bottom: 0, x: at, y: 0, toJSON: () => ({}) };
    });
    const client = new QueryClient();
    const at = (value: 'REACHING_OUT' | 'INTERESTED') => (
      <QueryClientProvider client={client}>
        <GaugeTrack customerId="c1" value={value} moves={[]} />
      </QueryClientProvider>
    );
    const { rerender } = render(at('REACHING_OUT'));
    const ring = () => screen.getByTestId('gauge-track').querySelector<HTMLElement>(':scope > span[aria-hidden]');
    expect(ring()).toHaveStyle({ left: '120px', width: '110px' });
    // The current node leans on the ring rather than drawing its own.
    expect(screen.getByText('Reaching out').closest('[aria-current]')).not.toHaveClass('ring-1');

    rerender(at('INTERESTED'));
    expect(ring()).toHaveStyle({ left: '360px' });
    expect(ring()).toHaveClass('duration-travel');
    boxes.mockRestore();
  });
});

describe('CheckRunway', () => {
  it('offers only the allowed moves, and "Propose" where a second officer must approve', () => {
    const onChoose = vi.fn();
    wrap(
      <CheckRunway
        value="IN_REVIEW"
        moves={[
          { to_value: 'CLEAR', reason_required: true, risk_required: true, approval_required: true },
          { to_value: 'MORE_INFO', reason_required: true, risk_required: false, approval_required: false },
        ]}
        onChoose={onChoose}
      />,
    );
    const runway = screen.getByTestId('check-runway');
    expect(within(runway).getAllByRole('button').map((b) => b.textContent)).toEqual([
      'More information needed',
      'Propose Clear',
    ]);
    fireEvent.click(within(runway).getByRole('button', { name: 'Propose Clear' }));
    expect(onChoose).toHaveBeenCalledWith('CLEAR');
  });

  it('draws an open proposal dashed, with the proposer signed and the approver waiting', () => {
    const proposal = {
      to_value: 'CLEAR',
      proposed_by: 'u1',
      proposed_by_name: 'R. Mehta',
      proposed_at: '2026-10-03T11:02:00Z',
    } as BackgroundCheckProposal;
    wrap(<CheckRunway value="IN_REVIEW" moves={[]} openProposal={proposal} />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    const signatures = screen.getByTestId('runway-signatures');
    expect(signatures).toHaveTextContent('Proposed by R. Mehta');
    expect(signatures).toHaveTextContent('Waiting for a second compliance officer');
  });
});

describe('Preflight', () => {
  it('shows the server’s sentence verbatim — never split into fake rows', () => {
    wrap(<Preflight blockedReason="the seller's background check is not clear; no pre-shipment document" />);
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent(
      "Not ready to hand over: the seller's background check is not clear; no pre-shipment document",
    );
    expect(screen.queryByRole('listitem')).not.toBeInTheDocument();
  });

  it('draws nothing without a reason (Developer is sent none)', () => {
    const { container } = wrap(<Preflight blockedReason={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('becomes a checklist once structured conditions are served', () => {
    wrap(
      <Preflight
        blockedReason="x"
        conditions={[
          { key: 'customer', met: true, message: 'Seller is a customer' },
          { key: 'buyer_aml', met: false, message: "Buyer's AML is not passed", fixAt: { to: '/companies/b', label: 'Record on buyer' } },
        ]}
      />,
    );
    expect(screen.getByText('1 of 2')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Record on buyer' })).toHaveAttribute('href', '/companies/b');
  });
});

describe('Shelf', () => {
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
      <Shelf
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

describe('SmartEntry', () => {
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
    wrap(<SmartEntry value="27AAAPL1234C1ZV" onChange={vi.fn()} name="Bharat Precision" country="IN" />);
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
    wrap(<SmartEntry value="Lakshmi Polymers" onChange={vi.fn()} country="IN" live={false} />);
    await new Promise((resolve) => setTimeout(resolve, 500));
    expect(matchCompany).not.toHaveBeenCalled();
  });
});

describe('PartyCard', () => {
  it('names the party, links to its dossier, and shows compliance to staff only', () => {
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
