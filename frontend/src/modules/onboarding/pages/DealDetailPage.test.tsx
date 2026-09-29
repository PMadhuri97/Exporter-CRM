import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import {
  createDownloadLink,
  fetchDocumentBlob,
  getDeal,
  getExporterProfileDetail,
  listDealDocuments,
  listDealHistory,
  listVerificationResults,
  setDealBuyer,
} from '../api';
import type { CrmDocument, Deal } from '../types';

import { DealDetailPage } from './DealDetailPage';

// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({
  getDeal: vi.fn(),
  listDealDocuments: vi.fn(),
  createDownloadLink: vi.fn(),
  fetchDocumentBlob: vi.fn(),
  getDocumentCategories: vi.fn(),
  setDealBuyer: vi.fn(),
  transitionDealStage: vi.fn(),
  uploadDealDocument: vi.fn(),
  // The page names the company in its back link, and shows the deal's history.
  getExporterProfileDetail: vi.fn(),
  listDealHistory: vi.fn(),
  // Staff see the buyer's checks under the buyer.
  listVerificationResults: vi.fn(),
}));

const DEAL_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';
const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

function deal(overrides: Partial<Deal> = {}): Deal {
  return {
    id: DEAL_ID,
    company_id: COMPANY_ID,
    reference: 'Rotterdam shipment, March',
    stage: 'GATHERING_PAPERWORK',
    withdrawal_reason: null,
    handed_over_at: null,
    created_at: '2026-03-01T10:00:00Z',
    updated_at: '2026-03-02T10:00:00Z',
    buyer: {
      id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      deal_id: DEAL_ID,
      name: 'Rotterdam Trading BV',
      country: 'NL',
      registration_number: 'NL-8899',
      tax_id: null,
      contact_email: null,
      contact_phone: null,
    },
    allowed_stage_moves: [{ to_stage: 'WITHDRAWN', reason_required: true }],
    handover_blocked_reason:
      'the company is PROSPECT, not CUSTOMER; the background check is FLAGGED, not CLEAR',
    ...overrides,
  };
}

function document_(overrides: Partial<CrmDocument> = {}): CrmDocument {
  return {
    id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    company_id: null,
    deal_id: DEAL_ID,
    category: 'SHIPPING',
    document_type: 'bill_of_lading',
    source: 'EXPORTER_UPLOAD',
    file_name: 'bill-of-lading.pdf',
    content_type: 'application/pdf',
    size_bytes: 2048,
    uploaded_by: 'someone',
    uploaded_at: '2026-03-02T10:00:00Z',
    scan_status: 'AVAILABLE',
    scanner_name: 'pass-through',
    is_downloadable: true,
    ...overrides,
  };
}

function signedInAs(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 'user-1',
    email: 'me@aner.example',
    full_name: 'Me',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/deals/${DEAL_ID}`]}>
        <Routes>
          <Route path="/deals/:dealId" element={<DealDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  signedInAs('OPERATIONS');
  vi.mocked(getDeal).mockResolvedValue(deal());
  vi.mocked(getExporterProfileDetail).mockResolvedValue({
    name: 'Acme Exports Pvt Ltd',
  } as Awaited<ReturnType<typeof getExporterProfileDetail>>);
  vi.mocked(listDealHistory).mockResolvedValue({ entries: [], total: 0, limit: 25, offset: 0 });
  vi.mocked(listVerificationResults).mockResolvedValue({
    entity_type: 'BUYER',
    entity_reference: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    results: [],
    total: 0,
    capabilities: { can_record_result: false, can_review: false },
  });
  vi.mocked(listDealDocuments).mockResolvedValue({
    documents: [document_()],
    total: 1,
    limit: 50,
    offset: 0,
  });
});

describe('DealDetailPage — the server decides what may happen next', () => {
  it('offers only the moves the server returned', async () => {
    renderPage();

    expect(await screen.findByRole('button', { name: 'Withdraw' })).toBeInTheDocument();
    // `HANDED_OVER` is absent from `allowed_stage_moves`, so it is not offered —
    // the page keeps no copy of the stage graph.
    expect(
      screen.queryByRole('button', { name: 'Hand over to lending' }),
    ).not.toBeInTheDocument();
  });

  it('explains a blocked handover instead of offering a button that would 409', async () => {
    renderPage();

    expect(await screen.findByText(/Not ready to hand over/)).toBeInTheDocument();
    // Every unmet condition, as the server names them.
    expect(
      screen.getByText(/not CUSTOMER; the background check is FLAGGED, not CLEAR/),
    ).toBeInTheDocument();
  });

  it('offers the handover when the server says it is allowed', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        allowed_stage_moves: [
          { to_stage: 'HANDED_OVER', reason_required: false },
          { to_stage: 'WITHDRAWN', reason_required: true },
        ],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    expect(
      await screen.findByRole('button', { name: 'Hand over to lending' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Not ready to hand over/)).not.toBeInTheDocument();
  });

  it('gives a DEVELOPER no stage controls at all', async () => {
    signedInAs('DEVELOPER');
    renderPage();

    expect(await screen.findByText('Rotterdam shipment, March')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Withdraw' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Edit buyer' }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Upload a document' }),
    ).not.toBeInTheDocument();
  });

  it('does not offer to edit the buyer of a handed-over deal', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'HANDED_OVER',
        handed_over_at: '2026-03-03T10:00:00Z',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    expect(await screen.findByText('Handed over')).toBeInTheDocument();
    // What the lending team was given must not be editable afterwards.
    expect(screen.queryByRole('button', { name: 'Edit buyer' })).not.toBeInTheDocument();
  });
});

describe('DealDetailPage — buyer checks', () => {
  it('shows staff the checks on the buyer, read through the buyer id', async () => {
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Buyer checks' })).toBeInTheDocument();
    expect(listVerificationResults).toHaveBeenCalledWith(
      'BUYER',
      'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
    );
  });

  it('does not render them for a DEVELOPER, whom the server refuses (D8)', async () => {
    signedInAs('DEVELOPER');
    renderPage();

    expect(await screen.findByText('Rotterdam shipment, March')).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Buyer checks' })).not.toBeInTheDocument();
    expect(listVerificationResults).not.toHaveBeenCalled();
  });

  it('has nothing to show before a buyer is recorded', async () => {
    vi.mocked(getDeal).mockResolvedValue(deal({ buyer: null }));
    renderPage();

    expect(await screen.findByText(/No buyer recorded yet/)).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Buyer checks' })).not.toBeInTheDocument();
  });
});

describe('DealDetailPage — documents', () => {
  it('names the scanner, so a pass-through is never mistaken for a scan', async () => {
    renderPage();

    await waitFor(() => expect(listDealDocuments).toHaveBeenCalled());
    expect(await screen.findByText('bill-of-lading.pdf')).toBeInTheDocument();
    expect(screen.getByText('Available')).toBeInTheDocument();
    expect(screen.getByText('pass-through')).toBeInTheDocument();
  });

  it('says a staff upload of the exporter’s paperwork came from the exporter, via staff', async () => {
    renderPage();

    expect(
      await screen.findByText(/From the exporter \(uploaded by staff\)/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Exporter Upload/)).not.toBeInTheDocument();
  });

  it('offers no download for a document that has not passed the scan step', async () => {
    vi.mocked(listDealDocuments).mockResolvedValue({
      documents: [
        document_({ scan_status: 'QUARANTINED', is_downloadable: false }),
      ],
      total: 1,
      limit: 50,
      offset: 0,
    });
    renderPage();

    expect(await screen.findByText('Quarantined')).toBeInTheDocument();
    // Absent, not disabled: a disabled button implies the file is one permission
    // away, and it is not — it is never served.
    expect(
      screen.queryByRole('button', { name: /^Download/ }),
    ).not.toBeInTheDocument();
  });

  it('shows an honest empty state when a deal has no paperwork', async () => {
    vi.mocked(listDealDocuments).mockResolvedValue({
      documents: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    renderPage();

    expect(
      await screen.findByText('No documents on this deal yet.'),
    ).toBeInTheDocument();
  });
});

describe("DealDetailPage — the review's findings", () => {
  it('downloads by fetching the content with the token, not by opening the URL', async () => {
    // `window.open` sends no Authorization header, and the content route is
    // role-gated, so opening the link returned 401 for every document. The click
    // must fetch the bytes and save them.
    vi.mocked(createDownloadLink).mockResolvedValue({
      document_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
      url: '/api/v1/onboarding/documents/content?key=k&expires=1&signature=s',
      expires_at: '2026-03-02T10:05:00Z',
    });
    vi.mocked(fetchDocumentBlob).mockResolvedValue(new Blob(['pdf bytes']));
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    const createObjectURL = vi.fn(() => 'blob:fake');
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() });

    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /^Download/ }));

    await waitFor(() => expect(fetchDocumentBlob).toHaveBeenCalledWith(
      '/api/v1/onboarding/documents/content?key=k&expires=1&signature=s',
    ));
    expect(createObjectURL).toHaveBeenCalled();
    // The old behaviour, and the bug: never open the URL directly.
    expect(open).not.toHaveBeenCalled();

    vi.unstubAllGlobals();
    open.mockRestore();
  });

  it('offers no upload on a handed-over deal, and says why', async () => {
    // The server refuses it (`DEAL_TERMINAL`): a handed-over deal's paperwork is
    // what the lending team was given.
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'HANDED_OVER',
        handed_over_at: '2026-03-03T10:00:00Z',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    expect(await screen.findByText(/has been handed over/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Upload a document' }),
    ).not.toBeInTheDocument();
  });

  it('offers no upload on a withdrawn deal either', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'WITHDRAWN',
        withdrawal_reason: 'Buyer cancelled',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    expect(await screen.findByText(/was withdrawn/)).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Upload a document' }),
    ).not.toBeInTheDocument();
  });

  it('asks before handing a deal over, because it cannot be undone', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        allowed_stage_moves: [{ to_stage: 'HANDED_OVER', reason_required: false }],
        handover_blocked_reason: null,
      }),
    );
    const { transitionDealStage } = await import('../api');

    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Hand over to lending' }),
    );

    // A dialog, not `window.confirm`: it can say what happens, and be tested.
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent(/cannot be undone/);
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    // Declined, so nothing was sent.
    expect(vi.mocked(transitionDealStage)).not.toHaveBeenCalled();
  });

  it('hands the deal over once the dialog is confirmed', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        allowed_stage_moves: [{ to_stage: 'HANDED_OVER', reason_required: false }],
        handover_blocked_reason: null,
      }),
    );
    const { transitionDealStage } = await import('../api');
    vi.mocked(transitionDealStage).mockResolvedValue(deal({ stage: 'HANDED_OVER' }));

    renderPage();
    fireEvent.click(
      await screen.findByRole('button', { name: 'Hand over to lending' }),
    );
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Hand over' }));
    await waitFor(() =>
      expect(vi.mocked(transitionDealStage)).toHaveBeenCalledWith(DEAL_ID, {
        to_stage: 'HANDED_OVER',
      }),
    );
  });
});

describe('DealDetailPage — editing a buyer whose details are masked', () => {
  // What OPERATIONS receives: the server masks the identifiers and contacts.
  const MASKED = deal({
    buyer: {
      id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
      deal_id: DEAL_ID,
      name: 'Rotterdam Trading BV',
      country: 'NL',
      registration_number: '•••8899',
      tax_id: '••••••••••9B01',
      contact_email: 'a•••@rotterdamtrading.example',
      contact_phone: '•••••••••••0101',
    },
  });

  beforeEach(() => {
    vi.mocked(setDealBuyer).mockResolvedValue(MASKED);
  });

  it('starts the masked fields empty and leaves them out, so the stored values are kept', async () => {
    vi.mocked(getDeal).mockResolvedValue(MASKED);
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit buyer' }));

    const taxId = screen.getByLabelText('Tax identifier');
    expect(taxId).toHaveValue('');
    expect(taxId).toHaveAttribute('placeholder', 'Hidden — type to replace');
    expect(screen.getByLabelText(/Buyer name/)).toHaveValue('Rotterdam Trading BV');

    fireEvent.change(screen.getByLabelText(/Buyer name/), {
      target: { value: 'Rotterdam Trading B.V.' },
    });
    fireEvent.change(screen.getByLabelText('Contact phone'), {
      target: { value: '+31 10 555 0199' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save buyer' }));

    await waitFor(() => expect(setDealBuyer).toHaveBeenCalled());
    const [, body] = vi.mocked(setDealBuyer).mock.calls[0] ?? [];
    // Typed: sent. Untouched and hidden: left out (kept). Never the bullets.
    expect(body).toEqual({
      name: 'Rotterdam Trading B.V.',
      country: 'NL',
      contact_phone: '+31 10 555 0199',
    });
  });

  it('prefills and sends every field for COMPLIANCE, who sees them in full', async () => {
    signedInAs('COMPLIANCE');
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Edit buyer' }));
    expect(screen.getByLabelText('Registration number')).toHaveValue('NL-8899');

    fireEvent.click(screen.getByRole('button', { name: 'Save buyer' }));
    await waitFor(() => expect(setDealBuyer).toHaveBeenCalled());
    const [, body] = vi.mocked(setDealBuyer).mock.calls[0] ?? [];
    expect(body).toEqual({
      name: 'Rotterdam Trading BV',
      country: 'NL',
      registration_number: 'NL-8899',
      tax_id: null,
      contact_email: null,
      contact_phone: null,
    });
  });
});
