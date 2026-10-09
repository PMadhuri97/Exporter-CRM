import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  getScreeningReview,
  listCheckCycles,
  listCompanyDocuments,
  updateScreeningReviewItem,
} from '../api';

import { ScreeningChecklist } from './ScreeningChecklist';
import {
  CATALOGUE,
  COMPANY_ID,
  crmDocument,
  DOCUMENT_ID,
  renderWithClient,
  screeningItem,
  screeningList,
} from '../testing/verification-fixtures';
import type { CheckCycle } from '../types';

vi.mock('../api', () => ({
  getScreeningReview: vi.fn(),
  getScreeningItemHistory: vi.fn(),
  updateScreeningReviewItem: vi.fn(),
  listCompanyDocuments: vi.fn(),
  listCheckCycles: vi.fn(),
  getDocument: vi.fn(),
  createDownloadLink: vi.fn(),
  fetchDocumentBlob: vi.fn(),
}));

function renderChecklist() {
  return renderWithClient(<ScreeningChecklist customerId={COMPANY_ID} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getScreeningReview).mockResolvedValue(screeningList());
  vi.mocked(updateScreeningReviewItem).mockResolvedValue(screeningItem());
});

describe('ScreeningChecklist — rendered from the server’s catalogue', () => {
  it('shows every catalogue item, in the server’s order, with its label and section', async () => {
    renderChecklist();
    const items = await screen.findAllByTestId('screening-item');
    expect(items.map((item) => item.getAttribute('data-item-key'))).toEqual(
      CATALOGUE.map((item) => item.key),
    );
    for (const item of CATALOGUE) {
      expect(screen.getByText(item.label)).toBeInTheDocument();
    }
    expect(screen.getAllByTestId('screening-section').map((s) => s.firstChild?.textContent)).toEqual([
      'Company checks',
      'Volume and activity',
      'EDD',
      'Exception',
    ]);
  });

  it('keeps no copy of its own: a different catalogue renders differently', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({
        catalogue: [
          { key: 'z-last-alphabetically', label: 'Served first', section: 'Second section' },
          { key: 'a-first-alphabetically', label: 'Served second', section: 'First section' },
        ],
      }),
    );
    renderChecklist();
    const items = await screen.findAllByTestId('screening-item');
    expect(items.map((item) => item.getAttribute('data-item-key'))).toEqual([
      'z-last-alphabetically',
      'a-first-alphabetically',
    ]);
    expect(screen.getAllByTestId('screening-section').map((s) => s.firstChild?.textContent)).toEqual([
      'Second section',
      'First section',
    ]);
    expect(screen.queryByText(CATALOGUE[0]!.label)).not.toBeInTheDocument();
  });

  it('counts progress against the catalogue', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({ items: [screeningItem({ item_key: 'address-physical', status: 'PASSED' })] }),
    );
    renderChecklist();
    // Seven items since `website-reviewed` retired.
    expect(await screen.findByText(/1\/7 items reviewed/)).toBeInTheDocument();
  });

  it('shows a saved decision on its item', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({
        items: [screeningItem({ item_key: 'payment-purpose', status: 'FAILED', comment: 'Volumes too high' })],
      }),
    );
    renderChecklist();
    const label = CATALOGUE.find((item) => item.key === 'payment-purpose')!.label;
    const select = await screen.findByLabelText(`${label} status`);
    expect(select).toHaveValue('FAILED');
    expect(screen.getByLabelText(`${label} comment`)).toHaveValue('Volumes too high');
  });

  it('never hides a decision stored under a key the catalogue does not define', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({
        items: [
          screeningItem({ id: '77777777-7777-4777-8777-777777777777', item_key: 'legacy-key', status: 'FAILED', comment: 'Old checklist' }),
        ],
      }),
    );
    renderChecklist();
    const unknown = await screen.findByTestId('unrecognised-item');
    expect(unknown).toHaveTextContent('legacy-key');
    expect(unknown).toHaveTextContent('Failed');
    expect(unknown).toHaveTextContent('Old checklist');
    expect(screen.getByText(/1 unrecognised/)).toBeInTheDocument();
  });
});

describe('ScreeningChecklist — the served capability decides', () => {
  it('lets a caller who may record a decision save one', async () => {
    renderChecklist();
    const label = CATALOGUE[0]!.label;
    const select = await screen.findByLabelText(`${label} status`);
    expect(select).toBeEnabled();
    fireEvent.change(select, { target: { value: 'PASSED' } });
    fireEvent.change(screen.getByLabelText(`${label} comment`), {
      target: { value: '  Site live and consistent  ' },
    });
    const card = select.closest('[data-testid="screening-item"]') as HTMLElement;
    fireEvent.click(within(card).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(updateScreeningReviewItem).toHaveBeenCalledWith(COMPANY_ID, 'address-physical', {
        status: 'PASSED',
        comment: 'Site live and consistent',
      }),
    );
  });

  it('shows the checklist read-only when the server says the caller may not record', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({ capabilities: { can_record_decision: false } }),
    );
    renderChecklist();
    const selects = await screen.findAllByRole('combobox');
    expect(selects).toHaveLength(CATALOGUE.length);
    for (const select of selects) expect(select).toBeDisabled();
    expect(screen.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });
});

describe('ScreeningChecklist — loading and errors', () => {
  it('shows a loading state first', () => {
    vi.mocked(getScreeningReview).mockReturnValue(new Promise(() => {}));
    renderChecklist();
    expect(screen.queryAllByTestId('screening-item')).toHaveLength(0);
    expect(screen.queryByText(/items reviewed/)).not.toBeInTheDocument();
  });

  it('says so when the checklist cannot be loaded', async () => {
    vi.mocked(getScreeningReview).mockRejectedValue(new Error('boom'));
    renderChecklist();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load checklist.');
  });
});

function cycle(overrides: Partial<CheckCycle> = {}): CheckCycle {
  return {
    id: 'cycle-2',
    company_id: COMPANY_ID,
    number: 2,
    kind: 'RE_KYC',
    reason: 'Annual review',
    started_at: '2026-10-01T09:00:00Z',
    started_by: 'officer-1',
    started_by_name: null,
    source: 'background_check_service.start_cycle',
    rules_version: 'clear-2026-10-01-7items',
    is_current: true,
    ...overrides,
  };
}

describe('ScreeningChecklist — evidence on an answer', () => {
  it('shows the evidence a saved answer was given', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({
        items: [
          screeningItem({
            item_key: 'address-physical',
            evidence_refs: [{ type: 'url', ref: 'https://maps.example.com/site' }],
          }),
        ],
      }),
    );
    renderChecklist();
    const card = (await screen.findAllByTestId('screening-item'))[0]!;
    expect(within(card).getByTestId('evidence')).toBeInTheDocument();
    expect(within(card).getByRole('link', { name: 'https://maps.example.com/site' })).toBeInTheDocument();
  });

  it('records an answer with a document and a link as evidence', async () => {
    vi.mocked(listCompanyDocuments).mockResolvedValue({
      documents: [crmDocument(), crmDocument({ id: 'quarantined', scan_status: 'QUARANTINED', file_name: 'bad.pdf' })],
      total: 2,
      limit: 50,
      offset: 0,
    });
    renderChecklist();
    const label = CATALOGUE[0]!.label;
    const select = await screen.findByLabelText(`${label} status`);
    const card = select.closest('[data-testid="screening-item"]') as HTMLElement;
    fireEvent.change(select, { target: { value: 'PASSED' } });
    fireEvent.click(within(card).getByRole('button', { name: 'Attach evidence' }));
    // Only a scanned-clean document is offered.
    fireEvent.click(await within(card).findByRole('checkbox', { name: 'registry-extract.pdf' }));
    expect(within(card).queryByText('bad.pdf')).not.toBeInTheDocument();
    fireEvent.change(within(card).getByLabelText('Evidence link'), {
      target: { value: 'https://registry.example.com/extract' },
    });
    fireEvent.click(within(card).getByRole('button', { name: 'Add link' }));
    fireEvent.click(within(card).getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(updateScreeningReviewItem).toHaveBeenCalledWith(COMPANY_ID, 'address-physical', {
        status: 'PASSED',
        comment: null,
        evidence_refs: [
          { type: 'document', ref: DOCUMENT_ID },
          { type: 'url', ref: 'https://registry.example.com/extract' },
        ],
      }),
    );
  });

  it('refuses a link that is not http(s) before sending anything', async () => {
    vi.mocked(listCompanyDocuments).mockResolvedValue({ documents: [], total: 0, limit: 50, offset: 0 });
    renderChecklist();
    const card = (await screen.findAllByTestId('screening-item'))[0]!;
    fireEvent.click(within(card).getByRole('button', { name: 'Attach evidence' }));
    fireEvent.change(within(card).getByLabelText('Evidence link'), {
      target: { value: 'javascript:alert(1)' },
    });
    fireEvent.click(within(card).getByRole('button', { name: 'Add link' }));
    expect(within(card).getByRole('alert')).toHaveTextContent('http:// or https://');
    expect(updateScreeningReviewItem).not.toHaveBeenCalled();
  });
});

describe('ScreeningChecklist — check cycles', () => {
  it('names the cycle it shows', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(screeningList({ cycle: cycle({ number: 1, kind: 'INITIAL', id: 'cycle-1' }) }));
    renderChecklist();
    expect(await screen.findByTestId('screening-cycle')).toHaveTextContent(
      'Cycle 1 · Initial check · started 01 Oct 2026',
    );
    // Cycle 1 has no earlier cycle to choose, so the cycles are not even fetched.
    expect(listCheckCycles).not.toHaveBeenCalled();
  });

  it('lets an earlier cycle be read, and the server makes it read-only', async () => {
    vi.mocked(getScreeningReview).mockImplementation(async (_customerId, cycleId) =>
      cycleId === 'cycle-1'
        ? screeningList({
            cycle: cycle({ id: 'cycle-1', number: 1, kind: 'INITIAL', is_current: false }),
            items: [screeningItem({ item_key: 'address-physical', cycle_id: 'cycle-1' })],
            capabilities: { can_record_decision: false },
          })
        : screeningList({ cycle: cycle() }),
    );
    vi.mocked(listCheckCycles).mockResolvedValue({
      cycles: [cycle({ id: 'cycle-1', number: 1, kind: 'INITIAL', is_current: false }), cycle()],
      current_cycle_id: 'cycle-2',
    });
    renderChecklist();
    const picker = await screen.findByLabelText('Check cycle');
    expect(screen.getByTestId('screening-cycle')).toHaveTextContent('Cycle 2 · Re-KYC');
    fireEvent.change(picker, { target: { value: 'cycle-1' } });
    await waitFor(() =>
      expect(screen.getByTestId('screening-cycle')).toHaveTextContent('earlier cycle, read-only'),
    );
    expect(getScreeningReview).toHaveBeenLastCalledWith(COMPANY_ID, 'cycle-1');
    const selects = await screen.findAllByRole('combobox', { name: /status$/ });
    for (const select of selects) expect(select).toBeDisabled();
  });
});
