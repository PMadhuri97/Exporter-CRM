/**
 * Identifier (frontend-plan §6.6): no reveal or copy control at all for a viewer who
 * may not read a tax identifier in full; a holder of `exporters:view_full_tax_id` gets
 * an eye that starts closed, and reads the value once they ask.
 *
 * Driven by the permission, which is what decides it — grant it to the relationship
 * manager and the eye appears for them too, with nothing to change here.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useCanRevealIdentifiers } from '@/platform/access';

import { Identifier } from './Identifier';

vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useCanRevealIdentifiers: vi.fn(),
}));

/** Whether this viewer holds `exporters:view_full_tax_id`. */
function mayReveal(held: boolean) {
  vi.mocked(useCanRevealIdentifiers).mockReturnValue(held);
}

beforeEach(() => vi.clearAllMocks());

describe('Identifier', () => {
  it('gives a viewer without the permission no reveal and no copy control', () => {
    mayReveal(false);
    render(<Identifier kind="PAN" value="••••••1234F" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText(/234F$/)).toBeInTheDocument();
  });

  it(
    'covers the value for a holder until the eye is opened, and covers it again',
    () => {
      mayReveal(true);
      const write = vi.fn().mockResolvedValue(undefined);
      Object.assign(navigator, { clipboard: { writeText: write } });
      render(<Identifier kind="PAN" value="AAAPL1234C" />);

      // Closed: the server sent the value in full, and the screen covers it anyway.
      expect(screen.queryByText('AAAPL1234C')).not.toBeInTheDocument();
      expect(screen.getByText('••••••234C')).toBeInTheDocument();
      // Nothing to copy while there is nothing on screen to have read.
      expect(screen.queryByRole('button', { name: 'Copy value' })).not.toBeInTheDocument();

      // Open.
      fireEvent.click(screen.getByRole('button', { name: 'Reveal value' }));
      expect(screen.getByText('AAAPL1234C')).toBeInTheDocument();
      expect(screen.getByRole('button', { name: 'Hide value' })).toHaveAttribute(
        'aria-pressed',
        'true',
      );
      fireEvent.click(screen.getByRole('button', { name: 'Copy value' }));
      expect(write).toHaveBeenCalledWith('AAAPL1234C');

      // Closed again — the toggle goes both ways, which is what it failed to do when
      // the value was shown in full whatever the eye said.
      fireEvent.click(screen.getByRole('button', { name: 'Hide value' }));
      expect(screen.queryByText('AAAPL1234C')).not.toBeInTheDocument();
      expect(screen.getByText('••••••234C')).toBeInTheDocument();
    },
  );

  it('shows a dash for nothing, permission or not', () => {
    mayReveal(true);
    render(<Identifier value={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
