/**
 * The context bar and the keyboard (frontend-plan §7.1, §7.4): a page's own trail
 * wins over the default one; the avatar menu holds the theme, My profile and Sign
 * out; a page's keys fire, but never while someone is typing.
 */

import { act, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useAuth, useCurrentUser } from '@/platform/auth';
import { ShellProvider, useCrumbs, usePageShortcuts, useShellState } from '@/platform/shell';

import { ContextBar } from './ContextBar';
import { useGlobalShortcuts } from './useGlobalShortcuts';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useAuth: vi.fn(),
  useCurrentUser: vi.fn(),
}));

const logout = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 7,
    email: 'ritu@example.com',
    full_name: 'Ritu Mehta',
    role: 'OPERATIONS',
    is_active: true,
  } as unknown as ReturnType<typeof useCurrentUser>);
  vi.mocked(useAuth).mockReturnValue({ logout } as unknown as ReturnType<typeof useAuth>);
});

function Page({ trail }: { trail?: boolean }) {
  useCrumbs(trail ? [{ label: 'Companies', to: '/companies' }, { label: 'Bharat Precision Metals' }] : null);
  return null;
}

function renderBar(path: string, page?: React.ReactNode) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <ShellProvider>
        {page}
        <ContextBar role="OPERATIONS" onOpenCommand={vi.fn()} />
      </ShellProvider>
    </MemoryRouter>,
  );
}

describe('ContextBar', () => {
  it('shows the module as the trail when the page sets none', () => {
    renderBar('/follow-ups', <Page />);
    const trail = screen.getByRole('navigation', { name: 'Breadcrumb' });
    expect(trail).toHaveTextContent('Agenda');
  });

  it('shows the page’s own trail, the last step being the page itself', () => {
    renderBar('/companies/x', <Page trail />);
    expect(screen.getByRole('link', { name: 'Companies' })).toHaveAttribute('href', '/companies');
    expect(screen.getByText('Bharat Precision Metals')).toHaveAttribute('aria-current', 'page');
  });

  it('keeps the theme, My profile and Sign out in the avatar menu', async () => {
    renderBar('/');
    const trigger = screen.getByRole('button', { name: /Account: Ritu Mehta, RM/ });
    trigger.focus();
    fireEvent.keyDown(trigger, { key: 'Enter' });
    expect(await screen.findByRole('menuitemradio', { name: 'Dark' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'My profile' })).toHaveAttribute('href', '/settings');
    fireEvent.click(screen.getByRole('menuitem', { name: 'Sign out' }));
    expect(logout).toHaveBeenCalled();
  });
});

function Keys({ onLog }: { onLog: () => void }) {
  usePageShortcuts([{ key: 'l', label: 'Log a call', run: onLog }]);
  return null;
}

/** The shell's key binding, fed the page keys registered in the provider. */
function BoundKeys() {
  const { shortcuts } = useShellState();
  useGlobalShortcuts({ role: 'OPERATIONS', openCommand: vi.fn(), openSheet: vi.fn(), pageShortcuts: shortcuts });
  return null;
}

function Shell({ onLog }: { onLog: () => void }) {
  return (
    <ShellProvider>
      <Keys onLog={onLog} />
      <BoundKeys />
      <input aria-label="Notes" />
    </ShellProvider>
  );
}

describe('the keyboard', () => {
  it('runs a page key, but not while typing in a field', () => {
    const onLog = vi.fn();
    render(
      <MemoryRouter>
        <Shell onLog={onLog} />
      </MemoryRouter>,
    );
    act(() => {
      fireEvent.keyDown(screen.getByRole('textbox', { name: 'Notes' }), { key: 'l' });
    });
    expect(onLog).not.toHaveBeenCalled();
    act(() => {
      fireEvent.keyDown(document.body, { key: 'l' });
    });
    expect(onLog).toHaveBeenCalledTimes(1);
  });
});
