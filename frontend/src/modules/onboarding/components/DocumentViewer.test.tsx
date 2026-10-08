import { render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { crmDocument } from '../testing/verification-fixtures';

import { DocumentViewer } from './DocumentViewer';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: () => ({
    id: 'u1',
    email: 'meera@aner.example',
    full_name: 'Meera Shah',
    role: 'OPERATIONS',
    is_active: true,
  }),
}));
// pdf.js draws on canvases, which jsdom does not have; the viewer's job is to hand the
// PDF to it, not to rasterise it here.
vi.mock('./PdfPages', () => ({
  PdfPages: ({ url, title }: { url: string; title: string }) => (
    <p data-testid="pdf-pages" data-url={url}>
      {title}
    </p>
  ),
}));

describe('DocumentViewer — read on screen', () => {
  it('draws a PDF with its own viewer, under the reader\'s mark, with no Download', () => {
    render(
      <DocumentViewer
        document_={crmDocument({ file_name: 'contract.docx' })}
        preview={{ url: 'blob:pdf', type: 'application/pdf' }}
        onClose={vi.fn()}
      />,
    );
    const viewer = screen.getByTestId('document-viewer');
    expect(within(viewer).getByTestId('pdf-pages')).toHaveAttribute('data-url', 'blob:pdf');
    // No browser PDF viewer, so no browser save or print button.
    expect(viewer.querySelector('iframe')).toBeNull();
    expect(within(viewer).getByTestId('document-watermark')).toHaveAttribute(
      'data-text',
      expect.stringMatching(/^Meera Shah · /),
    );
    expect(screen.queryByRole('button', { name: /Download/ })).not.toBeInTheDocument();
    expect(screen.getByText('Read on screen. Views are recorded.')).toBeInTheDocument();
  });

  it('offers Download only when it is given one to offer', () => {
    const onDownload = vi.fn();
    render(
      <DocumentViewer
        document_={crmDocument()}
        preview={{ url: 'blob:img', type: 'image/png' }}
        onClose={vi.fn()}
        onDownload={onDownload}
      />,
    );
    expect(screen.getByRole('img', { name: 'registry-extract.pdf' })).toHaveAttribute('src', 'blob:img');
    screen.getByRole('button', { name: /Download/ }).click();
    expect(onDownload).toHaveBeenCalledTimes(1);
  });
});
