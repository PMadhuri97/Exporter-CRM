import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import type { ReactElement } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

import { getBackgroundCheck } from '../api';
import { COMPANY_ID } from '../testing/verification-fixtures';
import type { BackgroundCheck } from '../types';

import { CompanyComplianceSummary } from './CompanyComplianceSummary';

vi.mock('../api', () => ({ getBackgroundCheck: vi.fn() }));

/** The summary links to the company's panel, so it renders inside a router. */
function renderWithClient(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function standing(overrides: Partial<BackgroundCheck> = {}): BackgroundCheck {
  return {
    company_id: COMPANY_ID,
    value: 'CLEAR',
    risk_rating: 'LOW',
    latest_decision_id: null,
    clearing_decision_id: null,
    decided_at: '2026-09-28T10:00:00Z',
    allowed_moves: [],
    clear_blocked_reasons: [],
    compliance: {
      is_clear: true,
      clear_expires_at: '2027-09-28T10:00:00Z',
      is_clear_current: true,
      sanctions: 'PASSED',
      aml: 'MISSING',
    },
    awaiting_approval: false,
    rekyc_due: false,
    ...overrides,
  };
}

beforeEach(() => vi.clearAllMocks());

describe('CompanyComplianceSummary', () => {
  it('shows the gauge, a current Clear with its expiry, and sanctions and AML as served', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(standing());
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    expect(await screen.findByTestId('background-check-gauge')).toHaveAttribute('data-value', 'CLEAR');
    expect(screen.getByTestId('compliance-expiry')).toHaveTextContent('Clear until 28 Sep 2027');
    expect(screen.getByTestId('compliance-sanctions')).toHaveAttribute('data-state', 'PASSED');
    expect(screen.getByTestId('compliance-aml')).toHaveTextContent('AML: Not checked');
    expect(getBackgroundCheck).toHaveBeenCalledWith(COMPANY_ID);
    expect(screen.getByTestId('compliance-panel-link')).toHaveAttribute(
      'href',
      `/companies/${COMPANY_ID}?tab=background-check`,
    );
  });

  it('renders the same for a buyer-only company: its own check, its own panel (P4-5, P4-11)', async () => {
    const BUYER_ID = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        company_id: BUYER_ID,
        value: 'IN_REVIEW',
        awaiting_approval: true,
        compliance: {
          is_clear: false,
          clear_expires_at: null,
          is_clear_current: false,
          sanctions: 'PASSED',
          aml: 'PASSED',
        },
      }),
    );
    renderWithClient(<CompanyComplianceSummary companyId={BUYER_ID} />);
    expect(await screen.findByTestId('awaiting-approval-badge')).toBeInTheDocument();
    expect(getBackgroundCheck).toHaveBeenCalledWith(BUYER_ID);
    expect(screen.getByTestId('compliance-panel-link')).toHaveAttribute(
      'href',
      `/companies/${BUYER_ID}?tab=background-check`,
    );
    expect(screen.queryByTestId('compliance-expiry')).not.toBeInTheDocument();
  });

  it('says an expired Clear is due for Re-KYC', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        compliance: {
          is_clear: true,
          clear_expires_at: '2026-01-01T00:00:00Z',
          is_clear_current: false,
          sanctions: 'FAILED',
          aml: 'PENDING',
        },
      }),
    );
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    expect(await screen.findByTestId('compliance-expiry')).toHaveTextContent(
      'Clear expired on 01 Jan 2026 — Re-KYC due',
    );
    expect(screen.getByTestId('compliance-sanctions')).toHaveTextContent('Sanctions: Failed');
  });

  it('shows no expiry when the company is not Clear', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({
        value: 'IN_REVIEW',
        compliance: {
          is_clear: false,
          clear_expires_at: null,
          is_clear_current: false,
          sanctions: 'MISSING',
          aml: 'MISSING',
        },
      }),
    );
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    await screen.findByTestId('background-check-gauge');
    expect(screen.queryByTestId('compliance-expiry')).not.toBeInTheDocument();
  });

  it('tells a role refused the background check (D8) that it is not available, not that it failed', async () => {
    vi.mocked(getBackgroundCheck).mockRejectedValue(
      new ApiError(403, 'DEVELOPER is not allowed', 'FORBIDDEN'),
    );
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    expect(
      await screen.findByText('Compliance details are not available to your role.'),
    ).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.queryByTestId('compliance-panel-link')).not.toBeInTheDocument();
  });

  it('carries the served "Awaiting approval" and "Re-KYC due" badges (P3-1c, P3-3c)', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(
      standing({ awaiting_approval: true, rekyc_due: true }),
    );
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    expect(await screen.findByTestId('awaiting-approval-badge')).toBeInTheDocument();
    expect(screen.getByTestId('rekyc-due-badge')).toHaveTextContent('Re-KYC due');
  });

  it('shows neither badge when the server reports neither', async () => {
    vi.mocked(getBackgroundCheck).mockResolvedValue(standing());
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    await screen.findByTestId('background-check-gauge');
    expect(screen.queryByTestId('awaiting-approval-badge')).not.toBeInTheDocument();
    expect(screen.queryByTestId('rekyc-due-badge')).not.toBeInTheDocument();
  });

  it('reports any other failure as an error', async () => {
    vi.mocked(getBackgroundCheck).mockRejectedValue(new Error('network'));
    renderWithClient(<CompanyComplianceSummary companyId={COMPANY_ID} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded');
  });
});
