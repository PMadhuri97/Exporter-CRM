import { screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { getDocument } from '../api';
import { crmDocument, DOCUMENT_ID, renderWithClient } from '../testing/verification-fixtures';

import { EvidenceList } from './EvidenceList';

vi.mock('../api', () => ({
  createDownloadLink: vi.fn(),
  fetchDocumentBlob: vi.fn(),
  getDocument: vi.fn(),
}));

const CITED = [{ type: 'document', ref: DOCUMENT_ID }];

beforeEach(() => {
  vi.clearAllMocks();
});

describe('EvidenceList — a cited document by name', () => {
  it('shows the file name once the document is read, and the short id until then', async () => {
    vi.mocked(getDocument).mockResolvedValue(crmDocument({ file_name: 'IEC-certificate.pdf' }));
    renderWithClient(<EvidenceList note={null} refs={CITED} />);
    const evidence = screen.getByTestId('evidence');

    expect(evidence).toHaveTextContent('Document 33333333…');
    expect(await within(evidence).findByTestId('evidence-document-name')).toHaveTextContent(
      'IEC-certificate.pdf',
    );
    expect(evidence).not.toHaveTextContent('Document 33333333…');
    expect(getDocument).toHaveBeenCalledWith(DOCUMENT_ID);
  });

  it('reads a document cited twice only once', async () => {
    vi.mocked(getDocument).mockResolvedValue(crmDocument({ file_name: 'IEC-certificate.pdf' }));
    renderWithClient(
      <>
        <EvidenceList note={null} refs={CITED} />
        <EvidenceList note={null} refs={CITED} />
      </>,
    );
    expect(await screen.findAllByTestId('evidence-document-name')).toHaveLength(2);
    expect(getDocument).toHaveBeenCalledTimes(1);
  });

  it('keeps the short id, and asks only once, when the read is refused', async () => {
    vi.mocked(getDocument).mockRejectedValue(
      new ApiError(403, 'You may not read this document.', 'FORBIDDEN'),
    );
    renderWithClient(<EvidenceList note={null} refs={CITED} />);
    const evidence = screen.getByTestId('evidence');

    await waitFor(() => expect(getDocument).toHaveBeenCalledTimes(1));
    expect(evidence).toHaveTextContent('Document 33333333…');
    expect(within(evidence).queryByTestId('evidence-document-name')).not.toBeInTheDocument();
    // A refused name is not an error the reader acted on: nothing is announced.
    expect(within(evidence).queryByRole('alert')).not.toBeInTheDocument();
    // The download control is still there; it shows the server's refusal when used.
    expect(
      within(evidence).getByRole('button', { name: `Download evidence document ${DOCUMENT_ID}` }),
    ).toBeInTheDocument();
  });

  it('reads nothing when no document is cited', () => {
    renderWithClient(
      <EvidenceList note="Seen on the registry." refs={[{ type: 'url', ref: 'https://x.example' }]} />,
    );
    expect(getDocument).not.toHaveBeenCalled();
  });
});
