import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCurrentUser } from '@/platform/auth';

import {
  getExporterProfileDetail,
  listExporterActivities,
  listExporterContacts,
  listVerificationResults,
  getDocumentRequirements,
  getScreeningReview,
  getBankActivity,
} from '../api';
import { PERMITTED_LIFECYCLE_TRANSITIONS } from '../constants';
import { lifecycleActionLabel } from '../components/LifecycleMoveControl';
import type { ExporterProfileDetail, VerificationResult } from '../types';

import { ExporterDetailPage } from './ExporterDetailPage';

vi.mock('@/platform/auth', () => ({ useCurrentUser: vi.fn() }));
vi.mock('../api', () => ({
  getExporterProfileDetail: vi.fn(),
  listExporterContacts: vi.fn(),
  listExporterActivities: vi.fn(),
  addExporterContact: vi.fn(),
  logExporterActivity: vi.fn(),
  transitionExporterLifecycle: vi.fn(),
  listVerificationResults: vi.fn(),
  triggerVerification: vi.fn(),
  reviewVerification: vi.fn(),
  getScreeningReview: vi.fn(),
  updateScreeningReviewItem: vi.fn(),
  getBankActivity: vi.fn(),
  getDocumentRequirements: vi.fn(),
}));

const DETAIL: ExporterProfileDetail = {
  customer_id: '11111111-1111-4111-8111-111111111111',
  gstin: '27ABCDE1234F1Z5',
  pan: 'ABCDE1234F',
  iec: '1234567890',
  source: 'MANUAL',
  relationship_manager: 'Jane RM',
  relationship_manager_user_id: '22222222-2222-4222-8222-222222222222',
  lifecycle_status: 'LEAD',
  industry: 'Textiles',
  export_markets: ['US', 'GB'],
  products: ['Garments'],
  year_established: 2019,
  website: 'https://example.com',
  date_added: '2026-09-21T00:00:00Z',
  created_at: '2026-09-21T00:00:00Z',
  updated_at: '2026-09-21T00:00:00Z',
  contacts: [],
  recent_activities: [],
  onboarding_history: [
    {
      onboarding_id: '33333333-3333-4333-8333-333333333333',
      status: 'DRAFT',
      legal_name: 'Acme Exports Pvt Ltd',
      initiated_at: null,
      completed_at: null,
      rejection_category: null,
    },
  ],
};

/**
 * `normalized_result` generates as `Record<string, never>`: the backend types it
 * `dict[str, Any]`, which carries no property information into the OpenAPI
 * schema, so nothing can be assigned to it without a cast. Production code has
 * the same problem and solves it the same way (`readRiskFactors` in
 * `VerificationSection.tsx` casts, then validates what came back). One helper
 * here rather than a cast at each use site.
 */
function normalized(value: object): VerificationResult['normalized_result'] {
  return value as unknown as VerificationResult['normalized_result'];
}

/**
 * A risk rating as `RiskRatingAdapter` actually returns one: banded CRITICAL,
 * reported under the adapter's own provider name (not "manual"), and carrying
 * the same factor payload `onboarding_request.risk_rating_factors` stores.
 */
const RISK_RATING_RESULT: VerificationResult = {
  id: '44444444-4444-4444-8444-444444444444',
  verification_type: 'RISK_RATING',
  entity_type: 'EXPORTER',
  entity_reference: '11111111-1111-4111-8111-111111111111',
  provider: 'aner-risk-rating',
  provider_reference: null,
  status: 'REVIEW',
  risk_level: 'CRITICAL',
  performed_at: '2026-09-24T10:00:00Z',
  valid_until: null,
  normalized_result: normalized({
    score: 145,
    risk_rating: 'CRITICAL',
    factors: [
      {
        factor: 'registration_country',
        value: 'IN',
        score: 20,
        detail: "registration_country 'IN' scores 20.",
      },
    ],
    edd_required: true,
    edd_reason: 'CRITICAL risk rating',
    config_version: '1.0',
  }),
  evidence_reference: null,
  reviewed_by: null,
  review_status: null,
  created_at: '2026-09-24T10:00:00Z',
  updated_at: '2026-09-24T10:00:00Z',
};

/** A dev placeholder row: PENDING forever, no provider ever ran it. */
const STUB_RESULT: VerificationResult = {
  ...RISK_RATING_RESULT,
  id: '55555555-5555-4555-8555-555555555555',
  verification_type: 'KYB',
  provider: 'manual',
  status: 'PENDING',
  risk_level: null,
  normalized_result: normalized({
    stub: true,
    message: 'Provider integration not configured.',
  }),
};

function mockUser(role: string, id: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id,
    email: 'user@aner.example',
    full_name: 'Jane RM',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- concise test fixture
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/exporters/${DETAIL.customer_id}`]}>
        <Routes>
          <Route path="/exporters/:customerId" element={<ExporterDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ExporterDetailPage — E9', () => {
  beforeEach(() => {
    vi.mocked(getExporterProfileDetail).mockResolvedValue(DETAIL);
    vi.mocked(listExporterContacts).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      contacts: [],
    });
    vi.mocked(listExporterActivities).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      activities: [],
    });
    vi.mocked(listVerificationResults).mockResolvedValue({
      entity_type: 'EXPORTER',
      entity_reference: DETAIL.customer_id,
      results: [],
      total: 0,
    });
    vi.mocked(getScreeningReview).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      items: [],
    });
    vi.mocked(getBankActivity).mockResolvedValue({
      customer_id: DETAIL.customer_id,
      connected_accounts: 0,
      last_synced_at: null,
      open_findings: 0,
      findings: [],
    });
    vi.mocked(getDocumentRequirements).mockResolvedValue({
      entity_type: 'CORPORATION',
      registration_country: 'IN',
      sector_code: 'Textiles',
      corridor_intent: null,
      declared_monthly_volume_usd: null,
      policy_version: '1.0',
      required_documents: [
        {
          document_type: 'certificate_of_incorporation',
          max_age_days: null,
          validity_description: 'Accepted regardless of age',
        },
        {
          document_type: 'proof_of_registered_address',
          max_age_days: 90,
          validity_description: 'Must be within 3 months',
        },
      ],
      total: 2,
    });
  });

  it('renders relationship sections safely with no contacts or activity', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    expect(await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' })).toBeInTheDocument();
    expect(screen.getByText('No contacts yet. Add the first person you work with.')).toBeInTheDocument();
    expect(screen.getByText('No activity logged yet.')).toBeInTheDocument();
    expect(await screen.findByText('No company screening results yet')).toBeInTheDocument();
  });

  it('masks identifiers and exposes no reveal control to non-owner OPERATIONS', async () => {
    mockUser('OPERATIONS', 'someone-else');
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getByText('••••••234F')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /reveal value/i })).not.toBeInTheDocument();
  });

  it('allows the assigned OPERATIONS user to reveal identifiers', async () => {
    mockUser('OPERATIONS', DETAIL.relationship_manager_user_id!);
    renderPage();
    await screen.findByRole('heading', { name: 'Acme Exports Pvt Ltd' });
    expect(screen.getAllByRole('button', { name: /reveal value/i })).toHaveLength(3);
  });

  it('defines only CONTACTED as the legal next state from LEAD', () => {
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.LEAD).toEqual(['CONTACTED']);
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.LEAD).not.toContain('ACTIVE');
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.LEAD).not.toContain('ONBOARDED');
  });

  // -- B2: required documents, read-only ------------------------------------

  it('lists the required documents for the profile, with no upload control', async () => {
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();
    expect(await screen.findByText('Certificate Of Incorporation')).toBeInTheDocument();
    expect(screen.getByText('Proof Of Registered Address')).toBeInTheDocument();
    // The validity window is the point of showing the list at all.
    expect(screen.getByText('Within 3 months')).toBeInTheDocument();
    expect(screen.getByText('Any age')).toBeInTheDocument();
    // Documents are a later phase. Nothing here may offer to collect one.
    expect(screen.queryByRole('button', { name: /upload/i })).not.toBeInTheDocument();
    expect(document.querySelector('input[type="file"]')).toBeNull();
  });

  // -- B3: the risk rating, and its provenance ------------------------------

  it('renders a real risk rating with its band, score and EDD reason', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue({
      entity_type: 'EXPORTER',
      entity_reference: DETAIL.customer_id,
      results: [RISK_RATING_RESULT],
      total: 1,
    });
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();

    expect(await screen.findByText('Risk rating')).toBeInTheDocument();
    // CRITICAL is the band added in Phase A; before it, this read HIGH.
    const band = await screen.findByText('Critical');
    expect(band).toBeInTheDocument();
    expect(band.className).toContain('bg-red-600');
    expect(screen.getByText(/score 145/)).toBeInTheDocument();
    expect(screen.getByText(/CRITICAL risk rating/)).toBeInTheDocument();
  });

  it('shows the rater as the source, never "manual"', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue({
      entity_type: 'EXPORTER',
      entity_reference: DETAIL.customer_id,
      results: [RISK_RATING_RESULT],
      total: 1,
    });
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();

    // The EXP-2 provenance guarantee, asserted rather than assumed: the
    // service persists the adapter's self-reported provider verbatim, so a
    // computed rating must name the rater.
    expect(await screen.findByText(/aner-risk-rating/)).toBeInTheDocument();
    expect(screen.queryByText('Not computed')).not.toBeInTheDocument();
  });

  it('marks a risk rating that did not come from the rater as not computed', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue({
      entity_type: 'EXPORTER',
      entity_reference: DETAIL.customer_id,
      results: [{ ...RISK_RATING_RESULT, provider: 'manual' }],
      total: 1,
    });
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();

    expect(await screen.findByText('Not computed')).toBeInTheDocument();
  });

  // -- Phase A guard, still intact ------------------------------------------

  it('keeps a PENDING stub unreviewable', async () => {
    vi.mocked(listVerificationResults).mockResolvedValue({
      entity_type: 'EXPORTER',
      entity_reference: DETAIL.customer_id,
      results: [STUB_RESULT],
      total: 1,
    });
    mockUser('COMPLIANCE', 'someone-else');
    renderPage();

    expect(await screen.findByText(/Placeholder record/)).toBeInTheDocument();
    // A recorded review is immutable by database trigger, so accepting a check
    // that never ran is unrecoverable.
    expect(screen.queryByRole('button', { name: 'Accepted' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Rejected' })).not.toBeInTheDocument();
  });

  it('keeps the compliance send-back label and both legal next states deterministic', () => {
    expect(PERMITTED_LIFECYCLE_TRANSITIONS.COMPLIANCE_REVIEW).toEqual([
      'DATA_COLLECTION',
      'ONBOARDED',
    ]);
    expect(lifecycleActionLabel('COMPLIANCE_REVIEW', 'DATA_COLLECTION')).toBe(
      'Send back to Data Collection',
    );
    expect(lifecycleActionLabel('COMPLIANCE_REVIEW', 'ONBOARDED')).toBe(
      'Move to Onboarded',
    );
  });

});
