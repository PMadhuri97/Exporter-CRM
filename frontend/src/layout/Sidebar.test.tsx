/**
 * The sidebar highlights exactly one row: the most specific one that matches.
 *
 * Plain `NavLink` matching lights every prefix, so on `/exporters/follow-ups` both
 * `Exporters` and `Follow-ups` were active at once.
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { Sidebar } from './Sidebar';

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Sidebar />
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
    renderAt('/exporters/follow-ups');
    expect(current()).toEqual(['Follow-ups']);
  });

  it('still highlights Exporters on a company page', () => {
    renderAt('/exporters/3f1c2b7e-0000-4000-8000-000000000001');
    expect(current()).toEqual(['Exporters']);
  });

  it('highlights Dashboard only on the root', () => {
    renderAt('/');
    expect(current()).toEqual(['Dashboard']);
  });
});
