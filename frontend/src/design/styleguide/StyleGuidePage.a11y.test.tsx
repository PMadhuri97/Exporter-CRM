/**
 * The style guide renders every primitive in both themes, so an axe pass over it is
 * the accessibility check for the design system (frontend-plan §11, §15).
 *
 * `color-contrast` is off here only because jsdom computes no colours: contrast is
 * proven separately, from the tokens themselves, in `tokens.contrast.test.ts`.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import axe from 'axe-core';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { StyleGuidePage } from './StyleGuidePage';

/** As the app mounts it: inside a query client (main.tsx) and a router. */
function renderGuide() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <MemoryRouter>
        <StyleGuidePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function violations(container: Element) {
  const results = await axe.run(container, {
    rules: { 'color-contrast': { enabled: false } },
  });
  return results.violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`);
}

describe('the style guide', () => {
  it('opens in light, and shows every primitive in a light and a dark pane', () => {
    renderGuide();
    expect(screen.getByTestId('styleguide-light')).toBeInTheDocument();
    expect(screen.queryByTestId('styleguide-dark')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('radio', { name: 'Both' }));
    expect(screen.getByTestId('styleguide-light')).toHaveAttribute('data-theme', 'light');
    expect(screen.getByTestId('styleguide-dark')).toHaveAttribute('data-theme', 'dark');
  });

  it.each(['Light', 'Dark'])('has no accessibility violations in the %s theme', async (theme) => {
    const { container } = renderGuide();
    fireEvent.click(screen.getByRole('radio', { name: theme }));
    expect(await violations(container)).toEqual([]);
  }, 30_000);
});
