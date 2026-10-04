/**
 * Identifier (frontend-plan §6.6): no reveal or copy control at all for a masked
 * role; compliance and admin read the value in full (as MaskedValue did), with the
 * eye and a copy control.
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

  it.each<UserRole>(['COMPLIANCE', 'ADMIN'])('shows %s the value in full, with the eye and copy', (role) => {
    as(role);
    const write = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText: write } });
    render(<Identifier kind="PAN" value="AAAPL1234C" />);

    expect(screen.getByText('AAAPL1234C')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Reveal value' }));
    expect(screen.getByRole('button', { name: 'Hide value' })).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(screen.getByRole('button', { name: 'Copy value' }));
    expect(write).toHaveBeenCalledWith('AAAPL1234C');
  });

  it('shows a dash for nothing', () => {
    as('ADMIN');
    render(<Identifier value={null} />);
    expect(screen.getByText('—')).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
