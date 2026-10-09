import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import {
  createDownloadLink,
  fetchDocumentBlob,
  getDeal,
  listDealRequiredDocuments,
  getExporterProfileDetail,
  listDealDocuments,
  listDealHistory,
  listGstRegistrations,
  listTradeRelationships,
  listVerificationResults,
  matchCompany,
  searchExporterProfiles,
  setDealBuyer,
  setDealInvoicingBranch,
} from '../api';
import type { CrmDocument, Deal, GstRegistration } from '../types';

import { DealDetailPage } from './DealDetailPage';

// Partial: the role helpers (`isStaffRole`, …) stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
// Saving a copy is `documents:download`, read from the server; this page's tests hold it.
vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useHasPermission: () => true,
}));
vi.mock('../api', () => ({
  getDeal: vi.fn(),
  listDealRequiredDocuments: vi.fn(),
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
  // Trade history, mounted only on a deal with a buyer company.
  listTradeRelationships: vi.fn(),
  getTradeRelationship: vi.fn(),
  getTradeInvoice: vi.fn(),
  recordDealPaymentOutcome: vi.fn(),
  // The invoicing branch: the seller's GST registrations, and the write.
  listGstRegistrations: vi.fn(),
  setDealInvoicingBranch: vi.fn(),
  // The buyer picker and creating a buyer company from it.
  searchExporterProfiles: vi.fn(),
  matchCompany: vi.fn(),
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
    // The three newer deal fields. This fixture has them null: the buyer is still
    // a `deal_buyer` row (the buyer migration fills the company link), nothing has
    // been handed over, and no invoicing branch is recorded.
    buyer_company: null,
    handover_snapshot: null,
    seller_gst_registration_id: null,
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
    has_preview: true,
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
  // The shelf marks the categories a handover needs; none are required here.
  vi.mocked(listDealRequiredDocuments).mockResolvedValue({ requirements: [], history: [], can_edit: false } as never);
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
  // A seller with no GST registration is not asked for an invoicing branch.
  vi.mocked(listGstRegistrations).mockResolvedValue({ registrations: [], flagged_count: 0 });
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

    expect(await screen.findByRole('heading', { name: 'Rotterdam shipment, March' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Withdraw' })).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: 'Edit buyer details' }),
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

    expect((await screen.findAllByText('Handed over')).length).toBeGreaterThan(0);
    // What the lending team was given must not be editable afterwards.
    expect(screen.queryByRole('button', { name: 'Edit buyer details' })).not.toBeInTheDocument();
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

  it('does not render them for a DEVELOPER, whom the server refuses', async () => {
    signedInAs('DEVELOPER');
    renderPage();

    expect(await screen.findByRole('heading', { name: 'Rotterdam shipment, March' })).toBeInTheDocument();
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
    // Said once above the list (frontend-plan §8.5), not repeated beside each row.
    expect(screen.getByText('Prototype: pass-through scanner')).toBeInTheDocument();
    expect(screen.queryByText('pass-through', { exact: true })).not.toBeInTheDocument();
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
    fireEvent.click(await screen.findByRole('button', { name: 'Edit buyer details' }));

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
    fireEvent.click(await screen.findByRole('button', { name: 'Edit buyer details' }));
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

// ── What was handed over ─────────────────────────────────────────

describe('the handover snapshot', () => {
  const SNAPSHOT = {
    buyer: {
      name: 'Rotterdam Trading BV',
      country: 'NL',
      registration_number: '•••8899',
      tax_id: null,
      contact_email: null,
      contact_phone: null,
    },
    buyer_company_id: null,
    document_ids: ['aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'],
    snapshot_source: 'taken_at_handover',
    snapshot_at: '2026-03-10T09:00:00Z',
  };

  it('is absent before the deal is handed over', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Rotterdam shipment, March' });
    expect(screen.queryByText('What was handed over')).not.toBeInTheDocument();
  });

  it('shows the buyer and the paperwork count once it exists, read-only', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'HANDED_OVER',
        handed_over_at: '2026-03-10T09:00:00Z',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
        handover_snapshot: SNAPSHOT,
      }),
    );
    renderPage();

    // Scoped to the panel's own `<section>`: the live buyer carries the same
    // name, and a page-wide query would not say which of the two it found.
    await screen.findByRole('heading', { name: 'What was handed over' });
    const panel = screen
      .getByRole('heading', { name: 'What was handed over' })
      .closest('section') as HTMLElement;
    expect(within(panel).getByText('Rotterdam Trading BV')).toBeInTheDocument();
    expect(within(panel).getByText('•••8899')).toBeInTheDocument();
    expect(within(panel).getByText(/1 document was included/)).toBeInTheDocument();
    expect(
      within(panel).getByText(/Recorded at the moment of the handover/),
    ).toBeInTheDocument();
    // Nothing here is editable: the database refuses to change a snapshot, so
    // offering a control would be a lie.
    expect(within(panel).queryByRole('button')).not.toBeInTheDocument();
  });

  it('says so when the snapshot was reconstructed rather than recorded', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'HANDED_OVER',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
        handover_snapshot: {
          ...SNAPSHOT,
          document_ids: [],
          snapshot_source: 'backfilled_from_deal_buyer',
        },
      }),
    );
    renderPage();

    expect(await screen.findByText(/Reconstructed from the records/)).toBeInTheDocument();
    expect(screen.getByText(/0 documents were included/)).toBeInTheDocument();
  });

  it('says the paperwork was not recorded rather than that there was none', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'HANDED_OVER',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
        handover_snapshot: {
          ...SNAPSHOT,
          document_ids: null,
          snapshot_source: 'backfilled_from_deal_buyer',
        },
      }),
    );
    renderPage();

    expect(
      await screen.findByText(/Which documents were included was not recorded/),
    ).toBeInTheDocument();
    expect(screen.queryByText(/0 documents were included/)).not.toBeInTheDocument();
  });
});

// ── The buyer as a company record ───────────────────────────────

describe('the buyer company', () => {
  it('is absent on every deal whose buyer is still a deal_buyer row', async () => {
    renderPage();
    await screen.findByRole('heading', { name: 'Rotterdam shipment, March' });
    expect(screen.queryByText('Buyer company')).not.toBeInTheDocument();
  });

  it('links to the company and shows its masked identifiers when one is recorded', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        buyer_company: {
          company_id: '99999999-9999-4999-8999-999999999999',
          name: 'Rotterdam Trading BV',
          country: 'NL',
          pipeline_status: null,
          pan: '••••••1234',
          cin: null,
        },
      }),
    );
    renderPage();

    await screen.findByText('Buyer company');
    const link = screen.getByRole('link', { name: 'Rotterdam Trading BV' });
    expect(link).toHaveAttribute('href', '/companies/99999999-9999-4999-8999-999999999999');
    expect(screen.getByText('••••••1234')).toBeInTheDocument();
  });

  // The trade history panel, mounted only where it has two companies to
  // pair. A deal whose buyer is still a `deal_buyer` row has one, so the panel is
  // absent rather than empty — an empty panel would imply these two have never
  // traded, when the truth is that nothing yet says who the buyer is.
  it('shows trade history only once the buyer is a company', async () => {
    vi.mocked(listTradeRelationships).mockResolvedValue({ relationships: [], total: 0 });

    renderPage();
    await screen.findByRole('heading', { name: 'Rotterdam shipment, March' });
    expect(screen.queryByTestId('trade-history-panel')).not.toBeInTheDocument();
    expect(listTradeRelationships).not.toHaveBeenCalled();

    vi.mocked(getDeal).mockResolvedValue(
      deal({
        buyer_company: {
          company_id: '99999999-9999-4999-8999-999999999999',
          name: 'Rotterdam Trading BV',
          country: 'NL',
          pipeline_status: null,
          pan: null,
          cin: null,
        },
      }),
    );
    renderPage();

    expect(await screen.findByTestId('trade-history-panel')).toBeInTheDocument();
    // The seller's side of the pair is the deal's own company, not the buyer's.
    await waitFor(() =>
      expect(listTradeRelationships).toHaveBeenCalledWith(COMPANY_ID, { as: 'seller' }),
    );
  });

  // The server refuses a payment outcome on a deal that has not been handed
  // over, so offering the control earlier would be offering a refusal.
  it('offers "Record outcome" only after the handover', async () => {
    vi.mocked(listTradeRelationships).mockResolvedValue({ relationships: [], total: 0 });
    const buyerCompany = {
      company_id: '99999999-9999-4999-8999-999999999999',
      name: 'Rotterdam Trading BV',
      country: 'NL',
      pipeline_status: null,
      pan: null,
      cin: null,
    };

    vi.mocked(getDeal).mockResolvedValue(deal({ buyer_company: buyerCompany }));
    renderPage();
    await screen.findByTestId('trade-history-panel');
    expect(screen.queryByRole('button', { name: 'Record outcome' })).not.toBeInTheDocument();

    vi.mocked(getDeal).mockResolvedValue(
      deal({
        buyer_company: buyerCompany,
        stage: 'HANDED_OVER',
        handed_over_at: '2026-04-01T10:00:00Z',
      }),
    );
    renderPage();
    expect(
      await screen.findByRole('button', { name: 'Record outcome' }),
    ).toBeInTheDocument();
  });
});

// The guard asks for an invoicing branch whenever the seller
// has an active GST registration, and this panel is the only way to record one.
describe('the invoicing branch', () => {
  const MAHARASHTRA = 'mmmmmmmm-mmmm-4mmm-8mmm-mmmmmmmmmmmm';
  const KARNATAKA = 'kkkkkkkk-kkkk-4kkk-8kkk-kkkkkkkkkkkk';
  const NOT_RECORDED = 'the invoicing branch is not recorded';

  function branch(overrides: Partial<GstRegistration> = {}): GstRegistration {
    return {
      id: MAHARASHTRA,
      customer_id: COMPANY_ID,
      // Masked by the server for OPERATIONS; the page shows it as served.
      gstin: '•••••••••••F1Z5',
      state_code: '27',
      state_name: 'Maharashtra',
      status: 'ACTIVE',
      address: null,
      flag_status: 'NONE',
      flag_reason: null,
      active: true,
      deactivated_at: null,
      created_at: '2026-03-01T00:00:00Z',
      verify_url: null,
      also_held_by: [],
      ...overrides,
    };
  }

  beforeEach(() => {
    vi.mocked(listGstRegistrations).mockResolvedValue({
      registrations: [
        branch(),
        branch({
          id: KARNATAKA,
          gstin: '•••••••••••G1Z3',
          state_code: '29',
          state_name: 'Karnataka',
        }),
      ],
      flagged_count: 0,
    });
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        allowed_stage_moves: [{ to_stage: 'WITHDRAWN', reason_required: true }],
        handover_blocked_reason: NOT_RECORDED,
      }),
    );
  });

  it("offers staff a choice of the seller's branches on an open deal", async () => {
    renderPage();

    const select = await screen.findByLabelText('Invoiced from');
    // The seller's registrations — the deal's own company, not the buyer's.
    expect(listGstRegistrations).toHaveBeenCalledWith(COMPANY_ID);
    expect(
      within(select).getByRole('option', { name: 'Maharashtra · •••••••••••F1Z5' }),
    ).toBeInTheDocument();
    expect(
      within(select).getByRole('option', { name: 'Karnataka · •••••••••••G1Z3' }),
    ).toBeInTheDocument();
  });

  it("shows the guard's message while it is missing, and says what it is asking for", async () => {
    renderPage();

    expect(await screen.findByText(/Not ready to hand over/)).toBeInTheDocument();
    expect(screen.getByText(NOT_RECORDED)).toBeInTheDocument();
    // The panel says the same from the guard's own facts, next to the remedy.
    expect(await screen.findByRole('status')).toHaveTextContent(/handover asks which one/);
  });

  it('records the chosen branch through PUT /deals/{id}/invoicing-branch, and the handover opens', async () => {
    vi.mocked(setDealInvoicingBranch).mockResolvedValue(
      deal({
        seller_gst_registration_id: KARNATAKA,
        allowed_stage_moves: [
          { to_stage: 'HANDED_OVER', reason_required: false },
          { to_stage: 'WITHDRAWN', reason_required: true },
        ],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    fireEvent.change(await screen.findByLabelText('Invoiced from'), {
      target: { value: KARNATAKA },
    });

    await waitFor(() =>
      expect(setDealInvoicingBranch).toHaveBeenCalledWith(DEAL_ID, {
        gst_registration_id: KARNATAKA,
      }),
    );
    // The response is the deal as it now stands: the branch is recorded and the guard
    // has nothing left to say.
    expect(
      await screen.findByRole('button', { name: 'Hand over to lending' }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText('Invoiced from')).toHaveValue(KARNATAKA);
    expect(screen.queryByText(NOT_RECORDED)).not.toBeInTheDocument();
  });

  it('shows the recorded branch as the current choice, with a way to clear it', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({ seller_gst_registration_id: MAHARASHTRA, handover_blocked_reason: null }),
    );
    renderPage();

    expect(await screen.findByLabelText('Invoiced from')).toHaveValue(MAHARASHTRA);
    expect(screen.getByRole('button', { name: 'Clear' })).toBeInTheDocument();
  });

  it('shows a handed-over deal its branch read-only, because it is frozen with the deal', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'HANDED_OVER',
        handed_over_at: '2026-04-01T10:00:00Z',
        seller_gst_registration_id: MAHARASHTRA,
        allowed_stage_moves: [],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    expect(await screen.findByText('Maharashtra')).toBeInTheDocument();
    expect(screen.getByText('•••••••••••F1Z5')).toBeInTheDocument();
    expect(screen.getByText(/Frozen with the deal/)).toBeInTheDocument();
    expect(screen.queryByLabelText('Invoiced from')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear' })).not.toBeInTheDocument();
  });

  it('offers no choice on a withdrawn deal either', async () => {
    vi.mocked(getDeal).mockResolvedValue(
      deal({
        stage: 'WITHDRAWN',
        withdrawal_reason: 'Buyer went elsewhere',
        allowed_stage_moves: [],
        handover_blocked_reason: null,
      }),
    );
    renderPage();

    expect(await screen.findByText('No invoicing branch was recorded.')).toBeInTheDocument();
    expect(screen.queryByLabelText('Invoiced from')).not.toBeInTheDocument();
  });

  it('gives a DEVELOPER the recorded branch and no control', async () => {
    signedInAs('DEVELOPER');
    vi.mocked(getDeal).mockResolvedValue(deal({ seller_gst_registration_id: MAHARASHTRA }));
    renderPage();

    expect(await screen.findByText('Maharashtra')).toBeInTheDocument();
    expect(screen.queryByLabelText('Invoiced from')).not.toBeInTheDocument();
    expect(setDealInvoicingBranch).not.toHaveBeenCalled();
  });
});

// A buyer not on file is created as a company outside the pipeline, through the
// deal's own buyer route, and named in the same request.
describe('creating the buyer company', () => {
  it('sends the create form to PUT /deals/{id}/buyer and closes the picker', async () => {
    vi.mocked(getDeal).mockResolvedValue(deal({ buyer: null }));
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 10, offset: 0 });
    vi.mocked(matchCompany).mockResolvedValue({
      kind: 'NEW',
      company_id: null,
      reason: null,
      needs_a_person: false,
      candidates: [],
    });
    vi.mocked(setDealBuyer).mockResolvedValue(
      deal({
        buyer: null,
        buyer_company: {
          company_id: '99999999-9999-4999-8999-999999999999',
          name: 'Brand New Buyer',
          country: 'IN',
          pipeline_status: 'NOT_IN_PIPELINE',
          pan: null,
          cin: null,
        },
      }),
    );
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Choose buyer company' }));
    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'Brand New Buyer' },
    });
    fireEvent.blur(screen.getByPlaceholderText('Company name'));
    fireEvent.click(await screen.findByRole('button', { name: 'Create buyer company' }));
    const form = screen.getByRole('form', { name: 'Create buyer company' });
    fireEvent.click(within(form).getByRole('button', { name: 'Create buyer company' }));

    await waitFor(() =>
      expect(setDealBuyer).toHaveBeenCalledWith(DEAL_ID, {
        create: {
          name: 'Brand New Buyer',
          country: 'IN',
          pan: null,
          gstin: null,
          registration_number: null,
        },
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole('form', { name: 'Create buyer company' })).not.toBeInTheDocument(),
    );
  });

  it('is not offered to a DEVELOPER, who cannot record a buyer at all', async () => {
    signedInAs('DEVELOPER');
    vi.mocked(getDeal).mockResolvedValue(deal({ buyer: null }));
    renderPage();
    await screen.findByRole('heading', { name: 'Rotterdam shipment, March' });
    expect(screen.queryByRole('button', { name: 'Choose buyer company' })).not.toBeInTheDocument();
  });
});
