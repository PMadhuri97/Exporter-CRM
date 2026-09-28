/**
 * The company screens moved from `/exporters/*` to `/companies/*` (and three of
 * them to the top level). Old bookmarks and pasted links must land on the same
 * screen, with their query string, and an unknown address must never be blank.
 */

import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { describe, expect, it } from 'vitest';

import { LegacyExporterRoutes } from './routes';

/** Stands in for every destination: prints where the redirect landed. */
function Landed() {
  const location = useLocation();
  return <p data-testid="landed">{`${location.pathname}${location.search}`}</p>;
}

function renderAt(url: string) {
  render(
    <MemoryRouter initialEntries={[url]}>
      <Routes>
        <Route path="/exporters/*" element={<LegacyExporterRoutes />} />
        <Route path="*" element={<Landed />} />
      </Routes>
    </MemoryRouter>,
  );
}

const ID = '11111111-1111-4111-8111-111111111111';

describe('LegacyExporterRoutes — the old /exporters addresses', () => {
  it.each([
    ['/exporters', '/companies'],
    ['/exporters/new', '/companies/new'],
    ['/exporters/import', '/companies/import'],
    ['/exporters/rxil-intake', '/companies/rxil-intake'],
    ['/exporters/follow-ups', '/follow-ups'],
    [`/exporters/deals/${ID}`, `/deals/${ID}`],
    [`/exporters/${ID}`, `/companies/${ID}`],
    [`/exporters/${ID}/documents`, `/companies/${ID}?tab=documents`],
    ['/exporters/a/b/c', '/companies'],
  ])('sends %s to %s', (from, to) => {
    renderAt(from);
    expect(screen.getByTestId('landed')).toHaveTextContent(to);
  });

  it('keeps the query string', () => {
    renderAt(`/exporters/${ID}/documents?from=email`);
    expect(screen.getByTestId('landed')).toHaveTextContent(
      `/companies/${ID}?tab=documents&from=email`,
    );
  });
});
