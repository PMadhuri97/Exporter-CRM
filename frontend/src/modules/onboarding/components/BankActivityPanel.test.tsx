import { screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { getBankActivity } from '../api';

import { BankActivityPanel } from './BankActivityPanel';
import { bankActivity, COMPANY_ID, renderWithClient } from './verification-test-fixtures';

vi.mock('../api', () => ({
  getBankActivity: vi.fn(),
}));

function renderPanel() {
  return renderWithClient(<BankActivityPanel customerId={COMPANY_ID} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(getBankActivity).mockResolvedValue(bankActivity());
});

describe('BankActivityPanel — honest about the missing feed', () => {
  it('says no provider feed is connected, in the server’s words', async () => {
    renderPanel();
    expect(await screen.findByTestId('bank-feed-status')).toHaveTextContent('Not connected');
    expect(
      screen.getByText(
        'No bank-monitoring provider feed is connected. Bank activity is not being monitored for this company.',
      ),
    ).toBeInTheDocument();
    expect(screen.getByText('Bank activity is not being monitored')).toBeInTheDocument();
    expect(screen.getByText(/this is not a clean result/)).toBeInTheDocument();
  });

  it('never presents zero accounts or zero flags as if something had been checked', async () => {
    renderPanel();
    await screen.findByTestId('bank-feed-status');
    expect(screen.queryByText('Connected accounts')).not.toBeInTheDocument();
    expect(screen.queryByText('Open suspicious activity flags')).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    expect(screen.queryByText('No bank activity findings')).not.toBeInTheDocument();
  });

  it('lists stored findings as stored, and invents none', async () => {
    vi.mocked(getBankActivity).mockResolvedValue(
      bankActivity({
        open_findings: 1,
        findings: [
          {
            id: '88888888-8888-4888-8888-888888888888',
            customer_id: COMPANY_ID,
            provider: 'surepass',
            finding_type: 'ROUND_TRIPPING',
            status: 'OPEN',
            risk_level: 'HIGH',
            title: 'Round-tripped receipts',
            description: null,
            provider_reference: null,
            detected_at: '2026-09-20T10:00:00Z',
            created_at: '2026-09-20T10:00:00Z',
          },
        ],
      }),
    );
    renderPanel();
    expect(await screen.findByText('Round-tripped receipts')).toBeInTheDocument();
    expect(screen.getByTestId('bank-feed-status')).toHaveTextContent('Not connected');
  });
});

describe('BankActivityPanel — loading and errors', () => {
  it('shows a loading state first', () => {
    vi.mocked(getBankActivity).mockReturnValue(new Promise(() => {}));
    renderPanel();
    expect(screen.queryByTestId('bank-feed-status')).not.toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('says so when bank activity cannot be loaded', async () => {
    vi.mocked(getBankActivity).mockRejectedValue(new Error('boom'));
    renderPanel();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load bank activity.');
  });
});
