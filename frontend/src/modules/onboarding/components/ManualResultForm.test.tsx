import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { listCompanyDocuments, listDealDocuments, triggerVerification } from '../api';

import { ManualResultForm } from './ManualResultForm';
import { COMPANY_CHECK_TYPES } from './verification-labels';
import {
  COMPANY_ID,
  crmDocument,
  DOCUMENT_ID,
  renderWithClient,
  verificationResult,
} from '../testing/verification-fixtures';

vi.mock('../api', () => ({
  listCompanyDocuments: vi.fn(),
  listDealDocuments: vi.fn(),
  triggerVerification: vi.fn(),
}));

const onClose = vi.fn();

function renderForm() {
  renderWithClient(
    <ManualResultForm
      entityType="EXPORTER"
      entityReference={COMPANY_ID}
      checkTypes={COMPANY_CHECK_TYPES}
      documentOwner={{ kind: 'company', id: COMPANY_ID }}
      onClose={onClose}
    />,
  );
  return screen.getByTestId('manual-result-form');
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listCompanyDocuments).mockResolvedValue({
    documents: [
      crmDocument(),
      crmDocument({
        id: '55555555-5555-4555-8555-555555555555',
        file_name: 'quarantined.pdf',
        scan_status: 'QUARANTINED',
        is_downloadable: false,
      }),
      crmDocument({
        id: '66666666-6666-4666-8666-666666666666',
        file_name: 'still-scanning.pdf',
        scan_status: 'PENDING_SCAN',
        is_downloadable: false,
      }),
    ],
    total: 3,
    limit: 50,
    offset: 0,
  });
  vi.mocked(triggerVerification).mockResolvedValue(verificationResult());
});

describe('ManualResultForm — what it offers', () => {
  it('never offers PENDING, and offers no provider choice', () => {
    const form = renderForm();
    const outcomes = within(within(form).getByLabelText('Outcome'))
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'));
    expect(outcomes).toEqual(['', 'PASSED', 'FAILED', 'REVIEW']);
    expect(within(form).queryByLabelText(/provider/i)).not.toBeInTheDocument();
    expect(within(form).queryByText(/rxil/i)).not.toBeInTheDocument();
  });

  it('offers the company check types', () => {
    const form = renderForm();
    const types = within(within(form).getByLabelText('Check'))
      .getAllByRole('option')
      .map((option) => option.getAttribute('value'));
    expect(types).toEqual(COMPANY_CHECK_TYPES);
  });

  it('labels the check types for a person: acronyms in capitals (R-60)', () => {
    const form = renderForm();
    const labels = within(within(form).getByLabelText('Check'))
      .getAllByRole('option')
      .map((option) => option.textContent);
    expect(labels).toEqual(expect.arrayContaining(['KYB', 'Company registry', 'IEC', 'GST']));
    expect(labels).not.toContain('Kyb');
    expect(labels).not.toContain('Iec');
  });

  it('offers only the company’s documents that can be opened', async () => {
    const form = renderForm();
    expect(await within(form).findByLabelText('registry-extract.pdf')).toBeInTheDocument();
    expect(within(form).queryByText('quarantined.pdf')).not.toBeInTheDocument();
    expect(within(form).queryByText('still-scanning.pdf')).not.toBeInTheDocument();
    expect(listCompanyDocuments).toHaveBeenCalledWith(COMPANY_ID, {});
    expect(listDealDocuments).not.toHaveBeenCalled();
  });

  it('says so when there is no document to attach', async () => {
    vi.mocked(listCompanyDocuments).mockResolvedValue({
      documents: [],
      total: 0,
      limit: 50,
      offset: 0,
    });
    const form = renderForm();
    expect(
      await within(form).findByText('No scanned-clean documents to attach.'),
    ).toBeInTheDocument();
  });
});

describe('ManualResultForm — the evidence rule (D16)', () => {
  it('refuses a PASSED with no evidence before calling the server', async () => {
    const form = renderForm();
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent(
      'A passed check needs evidence',
    );
    expect(triggerVerification).not.toHaveBeenCalled();
  });

  it('asks for an outcome first', async () => {
    const form = renderForm();
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));
    expect(await within(form).findByRole('alert')).toHaveTextContent('Choose an outcome.');
    expect(triggerVerification).not.toHaveBeenCalled();
  });

  it('records a PASSED resting on a selected document, as a manual result', async () => {
    const form = renderForm();
    fireEvent.click(await within(form).findByLabelText('registry-extract.pdf'));
    fireEvent.change(within(form).getByLabelText('Check'), { target: { value: 'SANCTIONS' } });
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    await waitFor(() => expect(triggerVerification).toHaveBeenCalledTimes(1));
    expect(triggerVerification).toHaveBeenCalledWith({
      verification_type: 'SANCTIONS',
      provider: 'manual',
      payload: { status: 'PASSED' },
      evidence_note: null,
      evidence_refs: [{ type: 'document', ref: DOCUMENT_ID }],
      entity_type: 'EXPORTER',
      entity_reference: COMPANY_ID,
    });
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('records a note, a link and a risk', async () => {
    const form = renderForm();
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'REVIEW' } });
    fireEvent.change(within(form).getByLabelText('Risk'), { target: { value: 'HIGH' } });
    fireEvent.change(within(form).getByLabelText('Evidence note'), {
      target: { value: '  Adverse press found  ' },
    });
    fireEvent.change(within(form).getByLabelText('Evidence link'), {
      target: { value: 'https://news.example/article' },
    });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    await waitFor(() => expect(triggerVerification).toHaveBeenCalledTimes(1));
    expect(triggerVerification).toHaveBeenCalledWith(
      expect.objectContaining({
        payload: { status: 'REVIEW', risk_level: 'HIGH' },
        evidence_note: 'Adverse press found',
        evidence_refs: [{ type: 'url', ref: 'https://news.example/article' }],
      }),
    );
  });

  it.each(['javascript:alert(1)', 'www.example.com'])(
    'refuses an evidence link that is not http(s) before calling the server: %s',
    async (link) => {
      const form = renderForm();
      fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
      fireEvent.change(within(form).getByLabelText('Evidence link'), { target: { value: link } });
      fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

      expect(await within(form).findByRole('alert')).toHaveTextContent(
        'The evidence link must start with http:// or https://.',
      );
      expect(triggerVerification).not.toHaveBeenCalled();
    },
  );

  it('lets a FAILED through without evidence', async () => {
    const form = renderForm();
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'FAILED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));
    await waitFor(() => expect(triggerVerification).toHaveBeenCalledTimes(1));
  });

  it('shows the server’s 422 as the server words it, and stays open', async () => {
    vi.mocked(triggerVerification).mockRejectedValue(
      new ApiError(
        422,
        `evidence document ${DOCUMENT_ID} is QUARANTINED: only an AVAILABLE (scanned clean) document can be evidence`,
        'VALIDATION_ERROR',
      ),
    );
    const form = renderForm();
    fireEvent.click(await within(form).findByLabelText('registry-extract.pdf'));
    fireEvent.change(within(form).getByLabelText('Outcome'), { target: { value: 'PASSED' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Record check' }));

    expect(await within(form).findByRole('alert')).toHaveTextContent('is QUARANTINED');
    expect(onClose).not.toHaveBeenCalled();
  });
});
