import { fireEvent, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getDecisionEvidence } from '../api';
import { COMPANY_ID, DOCUMENT_ID, renderWithClient } from '../testing/verification-fixtures';
import type { BackgroundCheckDecision, DecisionEvidence } from '../types';

import { DecisionHistory } from './DecisionHistory';

vi.mock('../api', () => ({
  getDecisionEvidence: vi.fn(),
  getDocument: vi.fn(),
  createDownloadLink: vi.fn(),
  fetchDocumentBlob: vi.fn(),
  fetchDocumentPreview: vi.fn(),
}));

// Saving a copy is `documents:download`, read from the server; these tests hold it unless
// they say otherwise.
const mayDownload = vi.hoisted(() => ({ value: true }));
vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useHasPermission: () => mayDownload.value,
}));

const DECISION_ID = 'dddddddd-dddd-4ddd-8ddd-dddddddddddd';

function decision(overrides: Partial<BackgroundCheckDecision> = {}): BackgroundCheckDecision {
  return {
    id: DECISION_ID,
    company_id: COMPANY_ID,
    from_value: 'IN_REVIEW',
    to_value: 'CLEAR',
    decided_by: 'maker',
    decided_by_name: 'Meera Iyer',
    decided_by_kind: 'MANUAL',
    source: 'MANUAL',
    decided_at: '2026-09-28T10:00:00Z',
    reason: 'All checks passed',
    risk_rating: 'LOW',
    supersedes_decision_id: null,
    evidence: [
      { kind: 'VERIFICATION_RESULT', verification_result_id: 'r1' },
      { kind: 'SCREENING_ITEM', screening_review_item_id: 's1' },
      { kind: 'DOCUMENT', crm_document_id: DOCUMENT_ID },
    ],
    rules_version: 'clear-2026-10-01-7items',
    cycle_id: 'cycle-1',
    cycle_number: 1,
    ...overrides,
  };
}

function evidence(overrides: Partial<DecisionEvidence> = {}): DecisionEvidence {
  return {
    decision_id: DECISION_ID,
    company_id: COMPANY_ID,
    to_value: 'CLEAR',
    rules_version: 'clear-2026-10-01-7items',
    cycle_id: 'cycle-1',
    cycle_number: 1,
    items: [
      {
        kind: 'VERIFICATION_RESULT',
        verification: {
          verification_result_id: 'r1',
          verification_type: 'SANCTIONS',
          status: 'PASSED',
          risk_level: null,
          provider: 'manual',
          provenance: 'MANUAL',
          is_placeholder: false,
          performed_at: '2026-09-27T09:00:00Z',
          recorded_by: 'officer-1',
          recorded_by_name: 'Anil Rao',
          evidence_note: 'World-Check clear',
          evidence_refs: [{ type: 'url', ref: 'https://screening.example.com/case/9' }],
          pinned_review: {
            id: 'rv1',
            review_status: 'ACCEPTED',
            reviewed_by: 'officer-2',
            reviewed_by_name: 'Priya Shah',
            reviewed_at: '2026-09-27T12:00:00Z',
            note: null,
          },
          review_superseded: true,
          cycle_id: 'cycle-1',
        },
        screening_item: null,
        document: null,
      },
      {
        kind: 'SCREENING_ITEM',
        verification: null,
        screening_item: {
          screening_review_item_id: 's1',
          item_key: 'website-reviewed',
          label: 'Has the website been reviewed?',
          retired: true,
          status: 'PASSED',
          comment: 'Site live',
          evidence_refs: [],
          reviewed_by: 'officer-1',
          reviewed_by_name: 'Anil Rao',
          reviewed_at: '2026-09-26T09:00:00Z',
          cycle_id: 'cycle-1',
        },
        document: null,
      },
      {
        kind: 'DOCUMENT',
        verification: null,
        screening_item: null,
        document: {
          crm_document_id: DOCUMENT_ID,
          file_name: 'registry-extract.pdf',
          category: 'COMPLIANCE_SCREENING',
          document_type: 'registry_extract',
          scan_status: 'AVAILABLE',
          is_downloadable: true,
          uploaded_by: null,
          uploaded_by_name: null,
          uploaded_at: '2026-09-25T09:00:00Z',
        },
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getDecisionEvidence).mockResolvedValue(evidence());
});

describe('DecisionHistory — the evidence behind each decision', () => {
  it('shows counts first and fetches nothing until a row is opened', () => {
    renderWithClient(
      <DecisionHistory decisions={[decision()]} isLoading={false} isError={false} customerId={COMPANY_ID} />,
    );
    expect(screen.getByTestId('evidence-summary')).toHaveTextContent(
      'Recorded against 1 document, 1 check, 1 screening item.',
    );
    expect(getDecisionEvidence).not.toHaveBeenCalled();
  });

  it('opens to each check with its result, who, when, provenance and evidence', async () => {
    renderWithClient(
      <DecisionHistory decisions={[decision()]} isLoading={false} isError={false} customerId={COMPANY_ID} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show evidence' }));
    const check = await screen.findByTestId('decision-evidence-check');
    expect(getDecisionEvidence).toHaveBeenCalledWith(COMPANY_ID, DECISION_ID);
    expect(check).toHaveTextContent('Sanctions check');
    expect(check).toHaveTextContent('Passed');
    expect(check).toHaveTextContent('Manual (person)');
    expect(check).toHaveTextContent('recorded by Anil Rao');
    expect(check).toHaveTextContent('Review relied on: Accepted by Priya Shah');
    expect(check).toHaveTextContent('World-Check clear');
    expect(within(check).getByRole('link', { name: 'https://screening.example.com/case/9' })).toHaveAttribute(
      'href',
      'https://screening.example.com/case/9',
    );
    // A review recorded since is flagged, never substituted for the one relied on.
    expect(within(check).getByTestId('review-superseded')).toBeInTheDocument();
    expect(screen.getByTestId('decision-evidence')).toHaveTextContent('seven-item checklist rules');
  });

  it('shows the exact screening answer — a retired item keeps its label — and the document', async () => {
    renderWithClient(
      <DecisionHistory decisions={[decision()]} isLoading={false} isError={false} customerId={COMPANY_ID} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show evidence' }));
    const answer = await screen.findByTestId('decision-evidence-screening');
    expect(answer).toHaveTextContent('Has the website been reviewed?');
    expect(answer).toHaveTextContent('Retired item');
    expect(answer).toHaveTextContent('Answered by Anil Rao');
    expect(answer).toHaveTextContent('Site live');
    const document = screen.getByTestId('decision-evidence-document');
    expect(document).toHaveTextContent('registry-extract.pdf');
    expect(within(document).getByRole('button', { name: /Download evidence document/ })).toBeInTheDocument();
  });

  it('names the eight-item rules for a decision taken before rules were versioned', async () => {
    vi.mocked(getDecisionEvidence).mockResolvedValue(
      evidence({ rules_version: 'clear-2026-09-28-8items', items: [] }),
    );
    renderWithClient(
      <DecisionHistory
        decisions={[decision({ rules_version: null })]}
        isLoading={false}
        isError={false}
        customerId={COMPANY_ID}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show evidence' }));
    expect(await screen.findByTestId('decision-evidence')).toHaveTextContent(
      'eight-item checklist rules',
    );
  });

  it('says so when the evidence cannot be loaded', async () => {
    vi.mocked(getDecisionEvidence).mockRejectedValue(new Error('boom'));
    renderWithClient(
      <DecisionHistory decisions={[decision()]} isLoading={false} isError={false} customerId={COMPANY_ID} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Show evidence' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded');
  });

  it('offers no evidence button when it is not told the company', () => {
    renderWithClient(<DecisionHistory decisions={[decision()]} isLoading={false} isError={false} />);
    expect(screen.queryByRole('button', { name: 'Show evidence' })).not.toBeInTheDocument();
  });
});

describe('DecisionHistory — cycles', () => {
  it('groups decisions by cycle, newest cycle first and marked current', () => {
    const decisions = [
      decision({ id: 'd3', from_value: 'CLEAR', to_value: 'IN_REVIEW', cycle_number: 2, cycle_id: 'cycle-2', reason: 'Re-KYC: annual' }),
      decision({ id: 'd2', cycle_number: 1 }),
      decision({ id: 'd1', from_value: 'NOT_STARTED', to_value: 'IN_REVIEW', cycle_number: 1, reason: null }),
    ];
    renderWithClient(
      <DecisionHistory decisions={decisions} isLoading={false} isError={false} customerId={COMPANY_ID} />,
    );
    const groups = screen.getAllByTestId('decision-cycle');
    expect(groups.map((group) => group.getAttribute('data-cycle'))).toEqual(['2', '1']);
    expect(groups[0]).toHaveTextContent('Cycle 2 (current)');
    expect(within(groups[0]!).getAllByTestId('decision-row')).toHaveLength(1);
    expect(within(groups[1]!).getAllByTestId('decision-row')).toHaveLength(2);
  });

  it('shows a single cycle as a plain list', () => {
    renderWithClient(
      <DecisionHistory decisions={[decision()]} isLoading={false} isError={false} customerId={COMPANY_ID} />,
    );
    expect(screen.queryByTestId('decision-cycle')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('decision-row')).toHaveLength(1);
  });
});
