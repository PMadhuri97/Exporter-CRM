import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UploadDocumentInput } from '../types';

import { DocumentsByCategory } from './record/DocumentsByCategory';

vi.mock('../hooks', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../hooks')>()),
  useDocumentCategories: () => ({
    isLoading: false,
    data: {
      scanner_name: 'clamav',
      categories: [
        { category: 'ENTITY_KYC', types: [{ key: 'PAN_CARD', label: 'PAN card' }, { key: 'GST_CERT', label: 'GST certificate' }] },
        { category: 'OTHER', types: [{ key: 'OTHER', label: 'Other' }] },
      ],
    },
  }),
}));

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

function file(name: string, size = 1024): File {
  const made = new File(['x'], name, { type: 'application/pdf' });
  Object.defineProperty(made, 'size', { value: size });
  return made;
}

function renderList(onUpload: (input: UploadDocumentInput) => Promise<unknown>) {
  wrap(
    <DocumentsByCategory
      isLoading={false}
      emptyMessage="None"
      documents={[]}
      upload={{ owner: 'COMPANY', onUpload }}
    />,
  );
}

function drop(files: File[]) {
  const zone = screen.getByText('Drop files here').closest('div')!;
  fireEvent.drop(zone, { dataTransfer: { files } });
}

function setAll(category: string, type: string) {
  fireEvent.change(screen.getByLabelText(/^Category( for all files)?$/), { target: { value: category } });
  fireEvent.change(screen.getByLabelText(/^Type( for all files)?$/), { target: { value: type } });
}

function rows() {
  return screen.getAllByTestId('upload-row');
}

type Upload = (input: UploadDocumentInput) => Promise<unknown>;

describe('uploading several documents at once', () => {
  let onUpload: ReturnType<typeof vi.fn<Upload>>;

  beforeEach(() => {
    onUpload = vi.fn<Upload>().mockResolvedValue({});
  });

  it('takes every dropped file, not just the first', async () => {
    renderList(onUpload);
    drop([file('a.pdf'), file('b.pdf'), file('c.pdf'), file('d.pdf'), file('e.pdf')]);
    expect(await screen.findByRole('list', { name: 'Files to upload' })).toBeInTheDocument();
    expect(rows()).toHaveLength(5);

    setAll('ENTITY_KYC', 'PAN_CARD');
    fireEvent.click(screen.getByRole('button', { name: 'Upload 5 files' }));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(5));
    expect(onUpload.mock.calls.map(([input]) => input.file.name).sort()).toEqual([
      'a.pdf',
      'b.pdf',
      'c.pdf',
      'd.pdf',
      'e.pdf',
    ]);
    expect(onUpload.mock.calls.every(([input]) => input.category === 'ENTITY_KYC' && input.documentType === 'PAN_CARD')).toBe(true);
  });

  it('sets category and type once for all files, and lets one row differ', async () => {
    renderList(onUpload);
    drop([file('pan.pdf'), file('gst.pdf')]);
    await screen.findByRole('list', { name: 'Files to upload' });
    setAll('ENTITY_KYC', 'PAN_CARD');
    fireEvent.change(screen.getByLabelText('Type for gst.pdf'), { target: { value: 'GST_CERT' } });
    fireEvent.click(screen.getByRole('button', { name: 'Upload 2 files' }));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(2));
    const byName = Object.fromEntries(onUpload.mock.calls.map(([input]) => [input.file.name, input.documentType]));
    expect(byName).toEqual({ 'pan.pdf': 'PAN_CARD', 'gst.pdf': 'GST_CERT' });
  });

  it('keeps the files that went up when one fails, and retries only the failed one', async () => {
    onUpload.mockImplementation(async ({ file: sent }: UploadDocumentInput) => {
      if (sent.name === 'bad.pdf') throw new Error('This file type is not accepted');
      return {};
    });
    renderList(onUpload);
    drop([file('one.pdf'), file('bad.pdf'), file('two.pdf')]);
    await screen.findByRole('list', { name: 'Files to upload' });
    setAll('OTHER', 'OTHER');
    fireEvent.click(screen.getByRole('button', { name: 'Upload 3 files' }));

    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(3));
    const failed = await screen.findByRole('alert');
    expect(failed).toHaveTextContent('This file type is not accepted');
    expect(rows().map((row) => row.getAttribute('data-status'))).toEqual(['done', 'failed', 'done']);

    onUpload.mockClear();
    onUpload.mockResolvedValue({});
    fireEvent.click(screen.getByRole('button', { name: 'Retry failed' }));
    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect(onUpload.mock.calls[0]![0].file.name).toBe('bad.pdf');
  });

  it('marks a file over the size limit at once and never sends it', async () => {
    renderList(onUpload);
    drop([file('ok.pdf'), file('huge.pdf', 30 * 1024 * 1024)]);
    await screen.findByRole('list', { name: 'Files to upload' });
    const huge = rows().find((row) => row.textContent?.includes('huge.pdf'))!;
    expect(within(huge).getByRole('alert')).toHaveTextContent('over the 25 MB limit');

    setAll('OTHER', 'OTHER');
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() => expect(onUpload).toHaveBeenCalledTimes(1));
    expect(onUpload.mock.calls[0]![0].file.name).toBe('ok.pdf');
  });

  it('takes at most ten files at a time', async () => {
    renderList(onUpload);
    drop(Array.from({ length: 12 }, (_, i) => file(`f${i}.pdf`)));
    await screen.findByRole('list', { name: 'Files to upload' });
    expect(rows()).toHaveLength(10);
  });

  it('still uploads a single file with one category and type', async () => {
    renderList(onUpload);
    drop([file('only.pdf')]);
    await screen.findByRole('list', { name: 'Files to upload' });
    expect(screen.queryByLabelText('Category for only.pdf')).not.toBeInTheDocument();
    setAll('ENTITY_KYC', 'PAN_CARD');
    fireEvent.click(screen.getByRole('button', { name: 'Upload' }));
    await waitFor(() =>
      expect(onUpload).toHaveBeenCalledWith(expect.objectContaining({ category: 'ENTITY_KYC', documentType: 'PAN_CARD' })),
    );
  });
});
