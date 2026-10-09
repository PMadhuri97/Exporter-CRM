/**
 * Identifier (frontend-plan §6.6): no reveal or copy control at all for a masked role;
 * compliance and admin get an eye that starts closed, and read the value once they ask.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { Identifier } from './Identifier';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));

function as(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ role } as ReturnType<typeof useCurrentUser>);
}

beforeEach(() => vi.clearAllMocks());

describe('Identifier', () => {
  it.each<UserRole>(['OPERATIONS', 'DEVELOPER'])('gives %s no reveal and no copy control', (role) => {
    as(role);
    render(<Identifier kind="PAN" value="••••••1234F" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
    expect(screen.getByText(/234F$/)).toBeInTheDocument();
  });

  it.each<UserRole>(['COMPLIANCE'])(
    'covers the value for %s until the eye is opened, and covers it again',
    (role) => {
      as(role);
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

  it('shows a dash for nothing', () => {
    as('ADMIN');
    render(<Identifier value={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
