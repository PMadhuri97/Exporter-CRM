import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { createDownloadLink, fetchDocumentBlob, getDocument } from '../api';
import type { VerificationResult } from '../types';

import { VerificationResultRow } from './VerificationResultRow';
import {
  COMPANY_ID,
  crmDocument,
  DOCUMENT_ID,
  renderWithClient,
  verificationResult,
} from './verification-test-fixtures';

vi.mock('../api', () => ({
  createDownloadLink: vi.fn(),
  fetchDocumentBlob: vi.fn(),
  getDocument: vi.fn(),
  reviewVerification: vi.fn(),
}));

function renderRow(result: VerificationResult, canReview = false) {
  renderWithClient(
    <VerificationResultRow
      result={result}
      customerId={COMPANY_ID}
      canReview={canReview}
      onStale={() => {}}
    />,
  );
  return screen.getByTestId('verification-result');
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('VerificationResultRow — provenance, as the server states it', () => {
  it('labels a manual result as a person’s', () => {
    const row = renderRow(verificationResult({ provenance: 'MANUAL', provider: 'manual' }));
    expect(row).toHaveTextContent('Manual (person)');
  });

  it('labels the RXIL stub as a stub, never as RXIL', () => {
    const row = renderRow(verificationResult({ provenance: 'STUB', provider: 'rxil_stub' }));
    expect(row).toHaveTextContent('RXIL stub, not RXIL');
    expect(row).not.toHaveTextContent('rxil_stub');
  });

  it('names a real provider by its stored name', () => {
    const row = renderRow(verificationResult({ provenance: 'PROVIDER', provider: 'surepass' }));
    expect(row).toHaveTextContent('SUREPASS');
  });

  it('labels a placeholder as never run, not as a check in flight', () => {
    const row = renderRow(verificationResult({ status: 'PENDING', is_placeholder: true }));
    expect(row).toHaveTextContent('Placeholder · no provider ran this check');
    expect(row).toHaveTextContent('Not run');
    expect(within(row).queryByText('Pending')).not.toBeInTheDocument();
  });

  it('takes placeholder status from the server, not from normalized_result.stub', () => {
    // The old client rule would have called this a placeholder; the server says it is not.
    const row = renderRow(
      verificationResult({
        status: 'PENDING',
        is_placeholder: false,
        normalized_result: { stub: true } as unknown as VerificationResult['normalized_result'],
      }),
    );
    expect(row).not.toHaveTextContent('Placeholder');
    expect(row).toHaveTextContent('Pending');
  });
});

describe('VerificationResultRow — evidence', () => {
  it('shows the note and the links as stored, and never the retired evidence_reference', () => {
    const row = renderRow(
      verificationResult({
        evidence_reference: 'LEGACY-REFERENCE',
        evidence_note: 'Registry extract matches the declared directors.',
        evidence_refs: [{ type: 'url', ref: 'https://registry.example/entity/1' }],
      }),
    );
    const evidence = within(row).getByTestId('evidence');
    expect(evidence).toHaveTextContent('Registry extract matches the declared directors.');
    expect(within(evidence).getByRole('link', { name: 'https://registry.example/entity/1' })).toHaveAttribute(
      'href',
      'https://registry.example/entity/1',
    );
    expect(row).not.toHaveTextContent('LEGACY-REFERENCE');
    expect(row).not.toHaveTextContent('Evidence reference');
  });

  it('shows no evidence block when there is none', () => {
    const row = renderRow(verificationResult());
    expect(within(row).queryByTestId('evidence')).not.toBeInTheDocument();
  });

  it('downloads a document through the existing download flow', async () => {
    vi.mocked(getDocument).mockResolvedValue(crmDocument());
    vi.mocked(createDownloadLink).mockResolvedValue({
      document_id: DOCUMENT_ID,
      url: '/api/v1/onboarding/documents/content?key=k&expires=1&signature=s',
      expires_at: '2026-09-28T10:05:00Z',
    });
    vi.mocked(fetchDocumentBlob).mockResolvedValue(new Blob(['pdf bytes']));
    const createObjectURL = vi.fn(() => 'blob:fake');
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL: vi.fn() });
    const open = vi.spyOn(window, 'open').mockImplementation(() => null);
    // jsdom cannot navigate to a blob URL; the save itself is the anchor's click.
    const save = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});

    const row = renderRow(
      verificationResult({ evidence_refs: [{ type: 'document', ref: DOCUMENT_ID }] }),
    );
    expect(row).toHaveTextContent('Document 33333333…');
    fireEvent.click(
      within(row).getByRole('button', { name: `Download evidence document ${DOCUMENT_ID}` }),
    );

    await waitFor(() =>
      expect(fetchDocumentBlob).toHaveBeenCalledWith(
        '/api/v1/onboarding/documents/content?key=k&expires=1&signature=s',
      ),
    );
    expect(getDocument).toHaveBeenCalledWith(DOCUMENT_ID);
    expect(createDownloadLink).toHaveBeenCalledWith(DOCUMENT_ID);
    expect(createObjectURL).toHaveBeenCalled();
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect(open).not.toHaveBeenCalled();
    open.mockRestore();
    save.mockRestore();
  });

  it('says so, and mints no link, for a document that cannot be served', async () => {
    vi.mocked(getDocument).mockResolvedValue(
      crmDocument({ scan_status: 'QUARANTINED', is_downloadable: false }),
    );
    const row = renderRow(
      verificationResult({ evidence_refs: [{ type: 'document', ref: DOCUMENT_ID }] }),
    );
    fireEvent.click(
      within(row).getByRole('button', { name: `Download evidence document ${DOCUMENT_ID}` }),
    );
    expect(await within(row).findByRole('alert')).toHaveTextContent(
      'registry-extract.pdf cannot be opened (QUARANTINED).',
    );
    expect(createDownloadLink).not.toHaveBeenCalled();
  });
});

describe('VerificationResultRow — review follows the served capability', () => {
  it('offers a review only when the caller may review', () => {
    renderRow(verificationResult(), false);
    expect(screen.queryByRole('button', { name: 'Review' })).not.toBeInTheDocument();
  });

  it('offers it when they may', () => {
    renderRow(verificationResult(), true);
    expect(screen.getByRole('button', { name: 'Review' })).toBeInTheDocument();
  });
});
