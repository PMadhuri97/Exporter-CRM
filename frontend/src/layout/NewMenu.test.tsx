/**
 * *+ New* in the app header (frontend-plan §6.1, §4.1): only the quick-create entries
 * the role has, and no menu at all for a role that may create nothing.
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

import type { UserRole } from '@/lib/api/types';
import { useCurrentUser } from '@/platform/auth';

import { NewMenu } from './NewMenu';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));

function renderAs(role: UserRole) {
  vi.mocked(useCurrentUser).mockReturnValue({ id: '1', role } as unknown as ReturnType<typeof useCurrentUser>);
  return render(
    <MemoryRouter>
      <NewMenu />
    </MemoryRouter>,
  );
}

function open() {
  const trigger = screen.getByRole('button', { name: /New/ });
  fireEvent.pointerDown(trigger, { button: 0, ctrlKey: false });
  fireEvent.keyDown(trigger, { key: 'Enter' });
}

describe('NewMenu', () => {
  it.each<UserRole>(['OPERATIONS', 'COMPLIANCE'])('offers %s New company, New deal and Import companies', async (role) => {
    renderAs(role);
    open();
    expect(await screen.findByRole('menuitem', { name: 'New company' })).toHaveAttribute('href', '/companies/new');
    // Opens the Deals page with its New deal panel open.
    expect(screen.getByRole('menuitem', { name: 'New deal' })).toHaveAttribute('href', '/deals?new=1');
    expect(screen.getByRole('menuitem', { name: 'Import companies' })).toHaveAttribute('href', '/companies/import');
  });

  it('offers no RXIL intake to OPERATIONS, whom the server refuses', async () => {
    renderAs('OPERATIONS');
    open();
    await screen.findByRole('menuitem', { name: 'New company' });
    expect(screen.queryByRole('menuitem', { name: 'RXIL intake' })).not.toBeInTheDocument();
  });

  it('adds RXIL intake for COMPLIANCE', async () => {
    renderAs('COMPLIANCE');
    open();
    expect(await screen.findByRole('menuitem', { name: 'RXIL intake' })).toHaveAttribute('href', '/companies/rxil-intake');
  });

  it.each<UserRole>(['DEVELOPER', 'ADMIN'])('is absent for %s, which may create nothing', (role) => {
    renderAs(role);
    expect(screen.queryByRole('button', { name: /New/ })).not.toBeInTheDocument();
  });
});
