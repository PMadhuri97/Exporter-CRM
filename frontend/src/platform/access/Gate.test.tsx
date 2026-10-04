import { render, screen } from '@testing-library/react';
import { lazy, Suspense } from 'react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { NOT_FOUND_TITLE } from '@/components';
import { useCurrentUser } from '@/platform/auth';

import { Gate } from './Gate';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useCurrentUser: vi.fn(),
}));

function signInAs(role: string) {
  vi.mocked(useCurrentUser).mockReturnValue({
    id: 'user-1',
    email: 'someone@aner.example',
    full_name: null,
    role,
    is_active: true,
  } as unknown as ReturnType<typeof useCurrentUser>);
}

/** A fresh lazy screen per test, whose "download" is observable. */
function lazyScreen() {
  const load = vi.fn(async () => ({ default: () => <p>the admin screen</p> }));
  return { Screen: lazy(load), load };
}

function renderGate(children: React.ReactNode) {
  return render(
    <MemoryRouter>
      <Suspense fallback={<p>loading</p>}>
        <Gate requires="settings.criteria">{children}</Gate>
      </Suspense>
    </MemoryRouter>,
  );
}

beforeEach(() => vi.clearAllMocks());

describe('Gate (R-33 Phase 0)', () => {
  it('renders, and only then loads, a screen the role may open', async () => {
    signInAs('ADMIN');
    const { Screen, load } = lazyScreen();
    renderGate(<Screen />);
    expect(await screen.findByText('the admin screen')).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(1);
  });

  it.each(['OPERATIONS', 'COMPLIANCE', 'DEVELOPER', 'API_USER', 'AUDITOR'])(
    'never downloads the screen for %s, and shows the generic NotFound',
    (role) => {
      signInAs(role);
      const { Screen, load } = lazyScreen();
      renderGate(<Screen />);
      expect(screen.getByRole('heading', { name: NOT_FOUND_TITLE })).toBeInTheDocument();
      expect(screen.queryByText(/administrator/i)).not.toBeInTheDocument();
      expect(load).not.toHaveBeenCalled();
    },
  );

  it('renders the fallback it is given instead, when there is one', () => {
    signInAs('API_USER');
    render(
      <Gate requires="crm.read" fallback={<p>no workspace</p>}>
        <p>the CRM</p>
      </Gate>,
    );
    expect(screen.getByText('no workspace')).toBeInTheDocument();
    expect(screen.queryByText('the CRM')).not.toBeInTheDocument();
  });
});
