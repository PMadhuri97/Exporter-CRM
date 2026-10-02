import { render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';

import { TradeHistoryPanel } from './TradeHistoryPanel';

const SELLER = 'ssssssss-ssss-4sss-8sss-ssssssssssss';
const BUYER = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';

it('says there is nothing recorded yet rather than showing invented rows', () => {
  render(<TradeHistoryPanel sellerId={SELLER} buyerId={BUYER} />);

  expect(screen.getByText('Trade history')).toBeInTheDocument();
  expect(screen.getByText(/not recorded yet/)).toBeInTheDocument();
});

it('renders without a dealId, for the company page', () => {
  render(<TradeHistoryPanel sellerId={SELLER} buyerId={BUYER} />);
  expect(screen.getByTestId('trade-history-panel')).toBeInTheDocument();
});

it('does not print the ids on screen', () => {
  // They are in the props because 3.22 needs them, but a panel that showed raw uuids
  // would read as half-built rather than as one waiting on a feature.
  const { container } = render(
    <TradeHistoryPanel
      sellerId={SELLER}
      buyerId={BUYER}
      dealId="dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    />,
  );
  expect(container.textContent).not.toContain(SELLER);
  expect(container.textContent).not.toContain(BUYER);
});
