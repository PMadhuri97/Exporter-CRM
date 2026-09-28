import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';
import { useCurrentUser } from '@/platform/auth';

import {
  addCriterionVersion,
  createCriterion,
  listCriteria,
  listCriterionVersions,
} from '../api';
import type { Criterion } from '../types';

import { QualificationCriteriaPage } from './QualificationCriteriaPage';

// Partial: the role helpers stay real, only the session is faked.
vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));
vi.mock('../api', () => ({
  listCriteria: vi.fn(),
  createCriterion: vi.fn(),
  listCriterionVersions: vi.fn(),
  addCriterionVersion: vi.fn(),
}));

const CRITERION: Criterion = {
  id: '33333333-3333-4333-8333-333333333333',
  key: 'annual_exports',
  version: 2,
  label: 'Annual exports',
  kind: 'NUMBER_THRESHOLD',
  comparison: 'AT_LEAST',
  threshold: 100000,
  unit: 'USD',
  allowed_values: null,
  required: true,
  active: true,
  created_by: 'admin-1',
  created_at: '2026-09-21T00:00:00Z',
};

function signedInAs(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 'user-1',
    email: 'admin@aner.example',
    full_name: null,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double
    role: role as any,
    is_active: true,
  });
}

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <QualificationCriteriaPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  signedInAs('ADMIN');
  vi.mocked(listCriteria).mockResolvedValue({ criteria: [CRITERION] });
});

describe('QualificationCriteriaPage (L2-09)', () => {
  it.each(['OPERATIONS', 'COMPLIANCE', 'DEVELOPER'])(
    'shows %s no criteria and no controls, since only ADMIN manages them',
    (role) => {
      signedInAs(role);
      renderPage();
      expect(screen.getByText('Administrators only')).toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /add criterion/i })).not.toBeInTheDocument();
    },
  );

  it('lists each criterion with its rule and version, and no edit or delete', async () => {
    renderPage();
    const row = await screen.findByTestId('criterion-row');
    expect(row).toHaveTextContent('Annual exports');
    expect(row).toHaveTextContent('at least 100000 USD');
    expect(row).toHaveTextContent('v2');
    expect(within(row).queryByRole('button', { name: /edit|delete/i })).not.toBeInTheDocument();
  });

  it('adds a criterion, sending only the fields its kind uses', async () => {
    vi.mocked(createCriterion).mockResolvedValue({ ...CRITERION, key: 'has_iec', version: 1 });
    renderPage();
    await screen.findByTestId('criterion-row');
    fireEvent.click(screen.getByRole('button', { name: 'Add criterion' }));

    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Key/), { target: { value: 'has_iec' } });
    fireEvent.change(within(dialog).getByLabelText(/^Label/), { target: { value: 'Holds an IEC' } });
    fireEvent.change(within(dialog).getByLabelText(/^Kind/), { target: { value: 'YES_NO' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Add criterion' }));

    await waitFor(() =>
      expect(createCriterion).toHaveBeenCalledWith({
        key: 'has_iec',
        label: 'Holds an IEC',
        kind: 'YES_NO',
        required: true,
        active: true,
        comparison: null,
        threshold: null,
        unit: null,
        allowed_values: null,
      }),
    );
  });

  it('adds a new version prefilled from the current one', async () => {
    vi.mocked(addCriterionVersion).mockResolvedValue({ ...CRITERION, version: 3 });
    renderPage();
    await screen.findByTestId('criterion-row');
    fireEvent.click(screen.getByRole('button', { name: 'New version of Annual exports' }));

    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText(/^Threshold/)).toHaveValue('100000');
    fireEvent.change(within(dialog).getByLabelText(/^Threshold/), { target: { value: '150000' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save new version' }));

    await waitFor(() =>
      expect(addCriterionVersion).toHaveBeenCalledWith(
        'annual_exports',
        expect.objectContaining({ threshold: 150000, comparison: 'AT_LEAST', unit: 'USD' }),
      ),
    );
  });

  it('says so when someone else changed the criterion first', async () => {
    vi.mocked(addCriterionVersion).mockRejectedValue(
      new ApiError(409, 'The criterion changed since you loaded it.', 'QUALIFICATION_CRITERION_CHANGED'),
    );
    renderPage();
    await screen.findByTestId('criterion-row');
    fireEvent.click(screen.getByRole('button', { name: 'New version of Annual exports' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save new version' }));

    expect(await within(dialog).findByRole('alert')).toHaveTextContent(/Someone else changed this criterion/);
  });

  it('shows every version, newest first', async () => {
    vi.mocked(listCriterionVersions).mockResolvedValue({
      criteria: [
        { ...CRITERION, id: 'v1', version: 1, threshold: 50000 },
        { ...CRITERION, id: 'v2', version: 2 },
      ],
    });
    renderPage();
    await screen.findByTestId('criterion-row');
    fireEvent.click(screen.getByRole('button', { name: /Versions/ }));
    const versions = await screen.findAllByTestId('criterion-version');
    expect(versions[0]).toHaveTextContent('v2');
    expect(versions[1]).toHaveTextContent('v1');
    expect(versions[1]).toHaveTextContent('at least 50000 USD');
  });
});
