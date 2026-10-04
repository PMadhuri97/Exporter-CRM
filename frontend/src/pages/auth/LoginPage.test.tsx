/**
 * Sign-in (frontend-plan §8.1). It had no test before Phase 2; the redesign changed
 * its look, so this pins its behaviour: the server's refusal in its words, the
 * client's checks before any request, and the redirect once signed in.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';
import { useAuth } from '@/platform/auth';

import { LoginPage } from './LoginPage';

vi.mock('@/platform/auth', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/auth')>()),
  useAuth: vi.fn(),
}));

const login = vi.fn();

function signedOut() {
  vi.mocked(useAuth).mockReturnValue({
    status: 'unauthenticated',
    user: null,
    login,
    logout: vi.fn(),
  } as unknown as ReturnType<typeof useAuth>);
}

function renderAt(state?: { from: string }) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: '/login', state }]}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<p>desk</p>} />
        <Route path="/companies" element={<p>companies</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  signedOut();
});

describe('LoginPage', () => {
  it('asks for an email and a password before sending anything', async () => {
    renderAt();
    expect(screen.getByRole('heading', { name: 'Sign in', level: 1 })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByText('Email is required')).toBeInTheDocument();
    expect(screen.getByText('Password is required')).toBeInTheDocument();
    expect(login).not.toHaveBeenCalled();
  });

  it('signs in with what was typed', async () => {
    login.mockResolvedValue(undefined);
    renderAt();
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rm@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'Secret123' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(login).toHaveBeenCalledWith('rm@example.com', 'Secret123'));
  });

  it('shows a refusal in the server’s words', async () => {
    login.mockRejectedValue(new ApiError(401, 'Email or password is incorrect.'));
    renderAt();
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'rm@example.com' } });
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'wrong' } });
    fireEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  });

  it('sends a signed-in user on to where they were going', () => {
    vi.mocked(useAuth).mockReturnValue({
      status: 'authenticated',
      user: { id: 1 },
      login,
      logout: vi.fn(),
    } as unknown as ReturnType<typeof useAuth>);
    renderAt({ from: '/companies' });
    expect(screen.getByText('companies')).toBeInTheDocument();
  });
});
