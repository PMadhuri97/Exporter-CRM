/**
 * Builders for Developer 4B's verification-workspace tests. Values are shaped like
 * the server's responses (the generated types), never hand-simplified.
 *
 * Test-only: imported by `*.test.tsx` files, never by the app — which is why it
 * lives in `testing/` rather than beside the components.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render } from '@testing-library/react';
import { createElement, type ReactElement } from 'react';

import type {
  BankActivityResponse,
  CrmDocument,
  ScreeningCatalogueItem,
  ScreeningItemHistory,
  ScreeningReviewItem,
  ScreeningReviewList,
  VerificationResult,
  VerificationResultList,
  VerificationReview,
} from '../types';

export const COMPANY_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
export const RESULT_ID = 'aaaaaaaa-0000-4000-8000-000000000001';
export const REVIEWER_ID = '22222222-2222-4222-8222-222222222222';
export const DOCUMENT_ID = '33333333-3333-4333-8333-333333333333';

export function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(createElement(QueryClientProvider, { client }, ui));
}

export function review(overrides: Partial<VerificationReview> = {}): VerificationReview {
  return {
    id: '11111111-1111-4111-8111-111111111111',
    verification_result_id: RESULT_ID,
    review_status: 'ACCEPTED',
    reviewed_by: REVIEWER_ID,
    reviewed_at: '2026-09-28T10:00:00Z',
    note: null,
    supersedes_review_id: null,
    ...overrides,
  };
}

export function verificationResult(
  overrides: Partial<VerificationResult> = {},
): VerificationResult {
  return {
    id: RESULT_ID,
    verification_type: 'KYB',
    entity_type: 'EXPORTER',
    entity_reference: COMPANY_ID,
    provider: 'manual',
    provenance: 'MANUAL',
    is_placeholder: false,
    provider_reference: null,
    status: 'REVIEW',
    risk_level: null,
    performed_at: '2026-09-28T09:00:00Z',
    valid_until: null,
    normalized_result: {},
    evidence_reference: null,
    evidence_note: null,
    evidence_refs: [],
    subject_snapshot: null,
    reviewed_by: null,
    review_status: null,
    latest_review_id: null,
    latest_reviewed_at: null,
    reviews: [],
    created_at: '2026-09-28T09:00:00Z',
    updated_at: '2026-09-28T09:00:00Z',
    ...overrides,
  };
}

export function resultList(
  results: VerificationResult[],
  capabilities = { can_record_result: true, can_review: true },
): VerificationResultList {
  return {
    entity_type: 'EXPORTER',
    entity_reference: COMPANY_ID,
    results,
    total: results.length,
    capabilities,
  };
}

export function crmDocument(overrides: Partial<CrmDocument> = {}): CrmDocument {
  return {
    id: DOCUMENT_ID,
    company_id: COMPANY_ID,
    deal_id: null,
    category: 'COMPLIANCE_SCREENING',
    document_type: 'registry_extract',
    source: 'INTERNAL',
    file_name: 'registry-extract.pdf',
    content_type: 'application/pdf',
    size_bytes: 1024,
    uploaded_by: null,
    uploaded_at: '2026-09-27T09:00:00Z',
    scan_status: 'AVAILABLE',
    scanner_name: 'pass-through',
    is_downloadable: true,
    ...overrides,
  };
}

/** The server's catalogue (`SCREENING_CATALOGUE_ITEMS`), in its display order — seven
 * items since plan P2-4a retired `website-reviewed`. */
export const CATALOGUE: ScreeningCatalogueItem[] = [
  { key: 'address-physical', label: 'Is the registered address a physical business address?', section: 'Company checks' },
  { key: 'business-consistency', label: 'Does the declared business activity make sense for the exporter?', section: 'Company checks' },
  { key: 'payment-purpose', label: 'Does expected payment and trading activity fit the business?', section: 'Volume and activity' },
  { key: 'bank-statements-reviewed', label: 'Have bank statements / bank-linked activity been reviewed?', section: 'EDD' },
  { key: 'suspicious-bank-indicators', label: 'Were suspicious bank activity indicators investigated?', section: 'EDD' },
  { key: 'exception-approval', label: 'If an exception exists, has it been formally approved?', section: 'Exception' },
  { key: 'exception-evidence', label: 'Has supporting evidence for the exception been attached?', section: 'Exception' },
];

export function screeningItem(overrides: Partial<ScreeningReviewItem> = {}): ScreeningReviewItem {
  return {
    id: '44444444-4444-4444-8444-444444444444',
    customer_id: COMPANY_ID,
    item_key: 'address-physical',
    status: 'PASSED',
    comment: null,
    reviewed_by: REVIEWER_ID,
    reviewed_at: '2026-09-28T10:00:00Z',
    created_at: '2026-09-28T10:00:00Z',
    updated_at: '2026-09-28T10:00:00Z',
    ...overrides,
  };
}

export function screeningList(
  overrides: Partial<ScreeningReviewList> = {},
): ScreeningReviewList {
  return {
    customer_id: COMPANY_ID,
    items: [],
    catalogue: CATALOGUE,
    capabilities: { can_record_decision: true },
    ...overrides,
  };
}

export function historyPage(
  items: ScreeningReviewItem[],
  { total = items.length, limit = 5, offset = 0 } = {},
): ScreeningItemHistory {
  return { customer_id: COMPANY_ID, item_key: 'address-physical', items, total, limit, offset };
}

export function bankActivity(
  overrides: Partial<BankActivityResponse> = {},
): BankActivityResponse {
  return {
    customer_id: COMPANY_ID,
    provider_feed_connected: false,
    provider_feed_status: 'NOT_CONNECTED',
    provider_feed_message:
      'No bank-monitoring provider feed is connected. Bank activity is not being monitored for this company.',
    connected_accounts: 0,
    last_synced_at: null,
    open_findings: 0,
    findings: [],
    ...overrides,
  };
}
