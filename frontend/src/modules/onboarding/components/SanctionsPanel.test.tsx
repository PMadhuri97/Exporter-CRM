import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import {
  confirmTrueMatch,
  decideSanctionsHit,
  getCompanySanctions,
  listSanctionsLists,
  recordSanctionsRun,
} from '../api';
import type { CompanySanctions, SanctionsRun } from '../types';

import { SanctionsPanel } from './SanctionsPanel';

vi.mock('../api', () => ({
  getCompanySanctions: vi.fn(),
  listSanctionsLists: vi.fn(),
  recordSanctionsRun: vi.fn(),
  decideSanctionsHit: vi.fn(),
  confirmTrueMatch: vi.fn(),
  rejectTrueMatch: vi.fn(),
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const COMPANY = 'c1';

function run(overrides: Partial<SanctionsRun> = {}): SanctionsRun {
  return {
    id: 'r1',
    company_id: COMPANY,
    subject_type: 'COMPANY',
    subject_name: 'Acme Exports',
    subject_reference: null,
    cycle_id: null,
    performed_by: 'u1',
    performed_by_name: 'Asha',
    performed_at: '2026-10-09T10:00:00Z',
    provider: 'MANUAL',
    provider_reference: null,
    search_terms: {},
    note: null,
    lists: [
      { code: 'UN_SC', list_version_date: '2026-10-09' },
      { code: 'IN_MHA_UAPA', list_version_date: '2026-10-09' },
    ],
    hits: [
      {
        id: 'h1',
        list_code: 'UN_SC',
        matched_name: 'Acme Exports Ltd',
        list_entry_id: 'QDe.123',
        score: '82',
        current: {
          id: 'd1',
          disposition: 'OPEN',
          reason: null,
          decided_by: 'u1',
          decided_by_name: 'Asha',
          decided_at: '2026-10-09T10:00:00Z',
          approved_by: null,
          approved_by_name: null,
        },
        decisions: [],
      },
    ],
    outcome: 'REVIEW',
    ...overrides,
  };
}

function standing(overrides: Partial<CompanySanctions> = {}): CompanySanctions {
  return {
    company_id: COMPANY,
    standing: 'REVIEW',
    flagged: false,
    can_record: true,
    true_match_approval: 'SECOND_OFFICER',
    subjects: [
      { subject_type: 'COMPANY', subject_name: 'Acme Exports', subject_reference: null, latest: run(), rescreen_reasons: [] },
      {
        subject_type: 'UBO',
        subject_name: 'Priya Shah',
        subject_reference: 'ubo-1',
        latest: null,
        rescreen_reasons: ['never screened'],
      },
    ],
    ...overrides,
  };
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SanctionsPanel customerId={COMPANY} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getCompanySanctions).mockResolvedValue(standing());
  vi.mocked(listSanctionsLists).mockResolvedValue({
    lists: [
      { id: 'l1', code: 'UN_SC', version: 1, name: 'UN Security Council Consolidated List', authority: null, active: true, mandatory: true, list_version_date: '2026-10-09', is_current: true },
      { id: 'l2', code: 'IN_MHA_UAPA', version: 1, name: 'India MHA / UAPA designated list', authority: null, active: true, mandatory: true, list_version_date: '2026-10-09', is_current: true },
    ],
    history: [],
    can_edit: false,
  });
  vi.mocked(recordSanctionsRun).mockResolvedValue(run({ outcome: 'PASSED', hits: [] }));
  vi.mocked(decideSanctionsHit).mockResolvedValue(run({ outcome: 'PASSED' }));
  vi.mocked(confirmTrueMatch).mockResolvedValue(run({ outcome: 'FAILED' }));
});

describe('SanctionsPanel', () => {
  it('shows each subject, its latest screening and who has never been screened', async () => {
    renderPanel();
    const subjects = await screen.findAllByTestId('sanctions-subject');
    expect(subjects).toHaveLength(2);
    expect(subjects[0]).toHaveTextContent('Under review');
    expect(subjects[0]).toHaveTextContent('UN_SC');
    expect(subjects[1]).toHaveTextContent('Priya Shah');
    expect(subjects[1]).toHaveTextContent('never screened');
  });

  it('records a clean screening against the mandatory lists', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: /Record screening/ }));
    await screen.findByText('UN Security Council Consolidated List');
    fireEvent.click(screen.getAllByRole('button', { name: 'Record screening' }).at(-1)!);

    await waitFor(() =>
      expect(recordSanctionsRun).toHaveBeenCalledWith(
        COMPANY,
        expect.objectContaining({
          subject_type: 'COMPANY',
          list_codes: ['UN_SC', 'IN_MHA_UAPA'],
          hits: [],
        }),
      ),
    );
  });

  it('marks a possible match a false positive, with a reason', async () => {
    renderPanel();
    fireEvent.click(await screen.findByRole('button', { name: 'Matches (1)' }));
    const hit = screen.getByTestId('sanctions-hit');
    fireEvent.click(within(hit).getByRole('button', { name: 'False positive' }));
    fireEvent.change(within(hit).getByLabelText(/^Why/), { target: { value: 'Different country' } });
    fireEvent.click(within(hit).getByRole('button', { name: 'Save decision' }));

    await waitFor(() => expect(decideSanctionsHit).toHaveBeenCalledWith('h1', 'FALSE_POSITIVE', 'Different country'));
  });

  it('flags the company and offers to confirm a proposed true match', async () => {
    const proposed = run();
    proposed.hits[0]!.current = { ...proposed.hits[0]!.current, disposition: 'TRUE_MATCH_PROPOSED', reason: 'Same director' };
    vi.mocked(getCompanySanctions).mockResolvedValue(
      standing({ flagged: true, subjects: [{ ...standing().subjects[0]!, latest: proposed }] }),
    );
    renderPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent('cannot be handed over');
    fireEvent.click(screen.getByRole('button', { name: 'Matches (1)' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm true match' }));
    await waitFor(() => expect(confirmTrueMatch).toHaveBeenCalledWith('h1'));
  });

  it('offers nothing to record to a reader', async () => {
    vi.mocked(getCompanySanctions).mockResolvedValue(standing({ can_record: false }));
    renderPanel();
    await screen.findAllByTestId('sanctions-subject');
    expect(screen.queryByRole('button', { name: /Record screening/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Screen' })).not.toBeInTheDocument();
  });
});
