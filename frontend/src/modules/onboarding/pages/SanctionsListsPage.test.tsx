/**
 * Sanctions lists decide what every screening must cover, so a change to one is a change
 * to a live compliance rule: Stop using asks first, and nothing is sent without a reason.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { addSanctionsList, listSanctionsLists, reviseSanctionsList } from '../api';
import type { SanctionsList } from '../types';

import { SanctionsListsPage } from './SanctionsListsPage';

vi.mock('../api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../api')>()),
  listSanctionsLists: vi.fn(),
  addSanctionsList: vi.fn(),
  reviseSanctionsList: vi.fn(),
}));

const REASON = 'CHG-3007: list withdrawn by the issuing authority';

const LIST: SanctionsList = {
  id: '55555555-5555-4555-8555-555555555555',
  code: 'UN_SC',
  version: 3,
  name: 'UN Security Council Consolidated List',
  authority: 'United Nations',
  active: true,
  mandatory: true,
  list_version_date: '2026-10-01',
  is_current: true,
  created_by: null,
  created_at: '2026-10-01T09:00:00Z',
  change_reason: null,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <SanctionsListsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listSanctionsLists).mockResolvedValue({ lists: [LIST], history: [LIST], can_edit: true });
  vi.mocked(reviseSanctionsList).mockResolvedValue({ ...LIST, version: 4, active: false });
  vi.mocked(addSanctionsList).mockResolvedValue(LIST);
});

describe('SanctionsListsPage', () => {
  it('asks before a list stops being used, and sends it with the reason given', async () => {
    renderPage();
    const row = await screen.findByTestId('sanctions-list-row');
    fireEvent.click(within(row).getByRole('button', { name: 'Stop using' }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('New screenings will no longer cover this list');
    const commit = within(dialog).getByRole('button', { name: 'Stop using list' });
    expect(commit).toBeDisabled();
    expect(reviseSanctionsList).not.toHaveBeenCalled();

    fireEvent.change(within(dialog).getByLabelText(/^Reason for change/), { target: { value: REASON } });
    fireEvent.click(commit);

    await waitFor(() =>
      expect(reviseSanctionsList).toHaveBeenCalledWith('UN_SC', { active: false, change_reason: REASON }),
    );
  });

  it('will not add a list without a reason', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Add a list/ }));

    fireEvent.change(screen.getByLabelText(/^Code/), { target: { value: 'EU_CONS' } });
    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'EU consolidated list' } });
    fireEvent.change(screen.getByLabelText(/^Version date/), { target: { value: '2026-10-10' } });
    expect(screen.getByRole('button', { name: 'Save list' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^Reason for change/), { target: { value: REASON } });
    fireEvent.click(screen.getByRole('button', { name: 'Save list' }));

    await waitFor(() =>
      expect(addSanctionsList).toHaveBeenCalledWith(expect.objectContaining({ code: 'EU_CONS', change_reason: REASON })),
    );
  });
});
