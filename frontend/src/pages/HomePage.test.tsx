/**
 * Which Home cards each role sees — Developer 1's compliance cards (plans P3-1c,
 * P3-3c). The cards themselves are tested in `HomeCards.test.tsx`; here they are stubs,
 * so only the page's choice of cards is under test.
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { HomePage } from './HomePage';

vi.mock('@/modules/onboarding', () => ({
  CheckBacksDueCard: () => <div data-testid="card-check-backs" />,
  FollowUpsDueCard: () => <div data-testid="card-follow-ups" />,
  PipelineSummaryCard: () => <div data-testid="card-pipeline" />,
  ProposalsAwaitingMeCard: () => <div data-testid="card-proposals" />,
  ReKycDueCard: () => <div data-testid="card-rekyc" />,
  paths: { newCompany: '/companies/new' },
}));

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));

function renderAs(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 1,
    email: 'someone@aner.example',
    full_name: 'Some One',
    role,
  } as unknown as ReturnType<typeof useCurrentUser>);
  return render(
    <MemoryRouter>
      <HomePage />
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe('HomePage — compliance cards by role', () => {
  it.each<UserRole>(['COMPLIANCE', 'ADMIN'])(
    'shows %s the approval queue and the Re-KYC list',
    (role) => {
      renderAs(role);
      expect(screen.getByTestId('card-proposals')).toBeInTheDocument();
      expect(screen.getByTestId('card-rekyc')).toBeInTheDocument();
    },
  );

  it('shows the RM the Re-KYC list but not the approval queue — the RM never approves', () => {
    renderAs('OPERATIONS');
    expect(screen.queryByTestId('card-proposals')).not.toBeInTheDocument();
    expect(screen.getByTestId('card-rekyc')).toBeInTheDocument();
  });

  it('shows DEVELOPER neither (the background-check routes refuse it, D8)', () => {
    renderAs('DEVELOPER');
    expect(screen.queryByTestId('card-proposals')).not.toBeInTheDocument();
    expect(screen.queryByTestId('card-rekyc')).not.toBeInTheDocument();
    expect(screen.getByTestId('card-pipeline')).toBeInTheDocument();
  });
});

describe('HomePage — Add company by role (R-33, G2)', () => {
  it.each<UserRole>(['OPERATIONS', 'COMPLIANCE', 'ADMIN'])('offers %s Add company', (role) => {
    renderAs(role);
    expect(screen.getByRole('link', { name: /Add company/ })).toHaveAttribute('href', '/companies/new');
  });

  it('offers DEVELOPER no Add company, which the server refuses it', () => {
    renderAs('DEVELOPER');
    expect(screen.queryByRole('link', { name: /Add company/ })).not.toBeInTheDocument();
  });
});
