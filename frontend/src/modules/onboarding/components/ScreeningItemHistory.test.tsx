import { fireEvent, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getScreeningItemHistory } from '../api';
import type { ScreeningChecklistStatus } from '../types';

import { ScreeningItemHistory } from './ScreeningItemHistory';
import {
  COMPANY_ID,
  historyPage,
  renderWithClient,
  screeningItem,
} from './verification-test-fixtures';

vi.mock('../api', () => ({
  getScreeningItemHistory: vi.fn(),
}));

const LABEL = 'Has the website been reviewed?';

function entry(n: number, status: ScreeningChecklistStatus, comment: string | null = null) {
  return screeningItem({
    id: `00000000-0000-4000-8000-00000000000${n}`,
    status,
    comment,
    reviewed_at: `2026-09-2${n}T10:00:00Z`,
  });
}

function renderHistory() {
  renderWithClient(
    <ScreeningItemHistory customerId={COMPANY_ID} itemKey="website-reviewed" label={LABEL} />,
  );
}

function open() {
  fireEvent.click(screen.getByRole('button', { name: `Show history for ${LABEL}` }));
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ScreeningItemHistory', () => {
  it('fetches nothing until it is opened', () => {
    renderHistory();
    expect(getScreeningItemHistory).not.toHaveBeenCalled();
  });

  it('shows the server’s history exactly as returned, newest first', async () => {
    vi.mocked(getScreeningItemHistory).mockResolvedValue(
      historyPage([
        entry(3, 'FAILED', 'Site offline again'),
        entry(2, 'PASSED', 'Site live'),
        entry(1, 'NEEDS_REVIEW'),
      ]),
    );
    renderHistory();
    open();

    const rows = await screen.findAllByTestId('screening-history-entry');
    expect(getScreeningItemHistory).toHaveBeenCalledWith(COMPANY_ID, 'website-reviewed', {
      limit: 5,
      offset: 0,
    });
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining('Failed'),
      expect.stringContaining('Passed'),
      expect.stringContaining('Needs Review'),
    ]);
    expect(rows[0]).toHaveTextContent('Site offline again');
    expect(screen.getByText('1–3 of 3')).toBeInTheDocument();
  });

  it('pages through a long history', async () => {
    vi.mocked(getScreeningItemHistory).mockImplementation(async (_c, _k, params) =>
      params?.offset === 5
        ? historyPage([entry(2, 'PASSED'), entry(1, 'NEEDS_REVIEW')], { total: 7, offset: 5 })
        : historyPage(
            [entry(7, 'FAILED'), entry(6, 'PASSED'), entry(5, 'FAILED'), entry(4, 'PASSED'), entry(3, 'FAILED')],
            { total: 7, offset: 0 },
          ),
    );
    renderHistory();
    open();

    expect(await screen.findByText('1–5 of 7')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Newer' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Older' }));

    expect(await screen.findByText('6–7 of 7')).toBeInTheDocument();
    expect(getScreeningItemHistory).toHaveBeenLastCalledWith(COMPANY_ID, 'website-reviewed', {
      limit: 5,
      offset: 5,
    });
    expect(screen.getAllByTestId('screening-history-entry')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Older' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Newer' })).toBeEnabled();
  });

  it('says so when nothing has been recorded', async () => {
    vi.mocked(getScreeningItemHistory).mockResolvedValue(historyPage([]));
    renderHistory();
    open();
    expect(
      await screen.findByText('No decision has been recorded on this item yet.'),
    ).toBeInTheDocument();
  });

  it('shows a loading state while the history is fetched', () => {
    vi.mocked(getScreeningItemHistory).mockReturnValue(new Promise(() => {}));
    renderHistory();
    open();
    expect(screen.getByText('Loading history…')).toBeInTheDocument();
  });

  it('says so when the history cannot be loaded, and can retry', async () => {
    vi.mocked(getScreeningItemHistory).mockRejectedValueOnce(new Error('boom'));
    vi.mocked(getScreeningItemHistory).mockResolvedValueOnce(historyPage([entry(1, 'PASSED')]));
    renderHistory();
    open();
    expect(await screen.findByRole('alert')).toHaveTextContent('The history could not be loaded.');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getAllByTestId('screening-history-entry')).toHaveLength(1));
  });

  it('closes again', async () => {
    vi.mocked(getScreeningItemHistory).mockResolvedValue(historyPage([entry(1, 'PASSED')]));
    renderHistory();
    open();
    await screen.findAllByTestId('screening-history-entry');
    fireEvent.click(screen.getByRole('button', { name: `Hide history for ${LABEL}` }));
    expect(screen.queryByTestId('screening-history-website-reviewed')).not.toBeInTheDocument();
  });
});
