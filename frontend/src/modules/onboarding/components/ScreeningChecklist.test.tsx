import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getScreeningReview, updateScreeningReviewItem } from '../api';

import { ScreeningChecklist } from './ScreeningChecklist';
import {
  CATALOGUE,
  COMPANY_ID,
  renderWithClient,
  screeningItem,
  screeningList,
} from './verification-test-fixtures';

vi.mock('../api', () => ({
  getScreeningReview: vi.fn(),
  getScreeningItemHistory: vi.fn(),
  updateScreeningReviewItem: vi.fn(),
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
      screeningList({ items: [screeningItem({ item_key: 'website-reviewed', status: 'PASSED' })] }),
    );
    renderChecklist();
    expect(await screen.findByText(/1\/8 items reviewed/)).toBeInTheDocument();
  });

  it('shows a saved decision on its item', async () => {
    vi.mocked(getScreeningReview).mockResolvedValue(
      screeningList({
        items: [screeningItem({ item_key: 'payment-purpose', status: 'FAILED', comment: 'Volumes too high' })],
      }),
    );
    renderChecklist();
    const select = await screen.findByLabelText(`${CATALOGUE[3]!.label} status`);
    expect(select).toHaveValue('FAILED');
    expect(screen.getByLabelText(`${CATALOGUE[3]!.label} comment`)).toHaveValue('Volumes too high');
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
      expect(updateScreeningReviewItem).toHaveBeenCalledWith(COMPANY_ID, 'website-reviewed', {
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
