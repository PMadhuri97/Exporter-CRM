/**
 * The rail (frontend-plan §7.1–7.2) highlights exactly one row — the most specific
 * one that matches — shows the settings rows to ADMIN only, keeps every row's name
 * while narrow, and remembers being pinned. Ported from the sidebar's tests when the
 * rail replaced it: Home is Desk, Follow-ups is Agenda, and Pipeline
 * is no longer a row (it is the Companies board).
 */

import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';

import type { UserRole } from '@/lib/api/types';

import { Rail } from './Rail';

function renderAt(path: string, role: UserRole = 'OPERATIONS') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Rail role={role} />
    </MemoryRouter>,
  );
}

function current(): string[] {
  return screen
    .getAllByRole('link')
    .filter((link) => link.getAttribute('aria-current') === 'page')
    .map((link) => link.textContent ?? '');
}

beforeEach(() => {
  window.localStorage.clear();
});

describe('Rail', () => {
  it('is the main navigation', () => {
    renderAt('/');
    expect(screen.getByRole('navigation', { name: 'Main' })).toBeInTheDocument();
  });

  it('highlights only Agenda on the agenda page', () => {
    renderAt('/follow-ups');
    expect(current()).toEqual(['Agenda']);
  });

  it('highlights Companies on a company page and on the board', () => {
    renderAt('/companies/3f1c2b7e-0000-4000-8000-000000000001');
    expect(current()).toEqual(['Companies']);
  });

  it('highlights Desk only on the root', () => {
    renderAt('/');
    expect(current()).toEqual(['Desk']);
  });

  it('links every main row to its screen, and has no Pipeline row', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Desk' })).toHaveAttribute('href', '/');
    expect(screen.getByRole('link', { name: 'Companies' })).toHaveAttribute('href', '/companies');
    expect(screen.getByRole('link', { name: 'Agenda' })).toHaveAttribute('href', '/follow-ups');
    expect(screen.getByRole('link', { name: 'Settings' })).toHaveAttribute('href', '/settings');
    expect(screen.queryByRole('link', { name: 'Pipeline' })).not.toBeInTheDocument();
  });

  it('shows the qualification criteria row to ADMIN, lit on its own page', () => {
    renderAt('/settings/qualification-criteria', 'ADMIN');
    expect(current()).toEqual(['Qualification criteria']);
  });

  it('shows the required documents row to ADMIN, lit on its own page', () => {
    renderAt('/settings/deal-required-documents', 'ADMIN');
    expect(current()).toEqual(['Required documents']);
    expect(screen.getByRole('link', { name: 'Required documents' })).toHaveAttribute(
      'href',
      '/settings/deal-required-documents',
    );
  });

  it.each<UserRole>(['OPERATIONS', 'COMPLIANCE', 'DEVELOPER'])(
    'shows no settings row to %s, whom the server refuses',
    (role) => {
      renderAt('/', role);
      expect(screen.queryByRole('link', { name: 'Qualification criteria' })).not.toBeInTheDocument();
      expect(screen.queryByRole('link', { name: 'Required documents' })).not.toBeInTheDocument();
    },
  );

  it('keeps every row named while narrow, and stays open once pinned', () => {
    const first = renderAt('/companies', 'ADMIN');
    expect(screen.getByRole('link', { name: 'Companies' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Qualification criteria' })).toBeInTheDocument();

    const pin = screen.getByRole('button', { name: 'Keep the menu open' });
    expect(pin).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(pin);
    expect(screen.getByRole('button', { name: 'Collapse the menu' })).toHaveAttribute('aria-pressed', 'true');

    // Remembered for this viewer.
    first.unmount();
    renderAt('/companies', 'ADMIN');
    expect(screen.getByRole('button', { name: 'Collapse the menu' })).toBeInTheDocument();
  });
});
