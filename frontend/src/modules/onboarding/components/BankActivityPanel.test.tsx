import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BankActivityPanel } from './BankActivityPanel';

describe('BankActivityPanel — honest about the missing feed', () => {
  it('says no bank-monitoring feed is connected', () => {
    render(<BankActivityPanel />);
    expect(screen.getByTestId('bank-feed-status')).toHaveTextContent('Not connected');
    expect(screen.getByText(/No bank-monitoring feed is connected/)).toBeInTheDocument();
    expect(screen.getByText('Bank activity is not being monitored')).toBeInTheDocument();
    expect(screen.getByText(/this is not a clean result/)).toBeInTheDocument();
  });

  it('never presents zero accounts or zero flags as if something had been checked', () => {
    render(<BankActivityPanel />);
    expect(screen.queryByText('Connected accounts')).not.toBeInTheDocument();
    expect(screen.queryByText('Open suspicious activity flags')).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });
});
