/**
 * The sidebar highlights exactly one row — the most specific one that
 * matches — and shows the Settings rows to ADMIN only.
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import type { UserRole } from '@/lib/api/types';

import { Sidebar } from './Sidebar';

function renderAt(path: string, role: UserRole = 'OPERATIONS') {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar role={role} />
    </MemoryRouter>,
  );
}

function current(): string[] {
  return screen
    .getAllByRole('link')
    .filter((link) => link.getAttribute('aria-current') === 'page')
    .map((link) => link.textContent ?? '');
}

describe('Sidebar', () => {
  it('highlights only Follow-ups on the Follow-ups page', () => {
    renderAt('/follow-ups');
    expect(current()).toEqual(['Follow-ups']);
  });

  it('highlights Companies on a company page', () => {
    renderAt('/companies/3f1c2b7e-0000-4000-8000-000000000001');
    expect(current()).toEqual(['Companies']);
  });

  it('highlights Home only on the root', () => {
    renderAt('/');
    expect(current()).toEqual(['Home']);
  });

  it('links every main row to its screen', () => {
    renderAt('/');
    expect(screen.getByRole('link', { name: 'Companies' })).toHaveAttribute('href', '/companies');
    expect(screen.getByRole('link', { name: 'Follow-ups' })).toHaveAttribute('href', '/follow-ups');
    expect(screen.getByRole('link', { name: 'Pipeline' })).toHaveAttribute('href', '/pipeline');
  });

  it('shows the qualification criteria row to ADMIN', () => {
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

  it('keeps a label for every row when collapsed to the icon rail', () => {
    render(
      <MemoryRouter initialEntries={['/pipeline']}>
        <Sidebar role="ADMIN" collapsed />
      </MemoryRouter>,
    );
    expect(screen.getByRole('link', { name: 'Pipeline' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Qualification criteria' })).toBeInTheDocument();
  });
});
