/**
 * Choosing a company by name — and never offering one nobody searched for.
 */

import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it, vi } from 'vitest';

import { searchExporterProfiles } from '../api';
import type { ExporterProfileListItem, ExporterSearchParams } from '../types';

import { CompanySearchSelect } from './CompanySearchSelect';

type ExporterProfileList = Awaited<ReturnType<typeof searchExporterProfiles>>;

vi.mock('../api', () => ({
  searchExporterProfiles: vi.fn(),
  getExporterProfileDetail: vi.fn(),
}));

function company(id: string, name: string | null): ExporterProfileListItem {
  return { customer_id: id, name, country: 'IN', journey: 'PROSPECT', pipeline_status: 'IN_PIPELINE' } as ExporterProfileListItem;
}

function list(...profiles: ExporterProfileListItem[]): ExporterProfileList {
  return { profiles, limit: 10, offset: 0 } as ExporterProfileList;
}

function Harness({ onChange }: { onChange: (id: string | null) => void }) {
  const [value, setValue] = useState<string | null>(null);
  return (
    <CompanySearchSelect
      label="Seller"
      value={value}
      onChange={(id) => {
        setValue(id);
        onChange(id);
      }}
    />
  );
}

function renderSelect(onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <Harness onChange={onChange} />
    </QueryClientProvider>,
  );
  return onChange;
}

describe('CompanySearchSelect', () => {
  it('never offers the row fetched before searching as a match while the search loads', async () => {
    let answerSearch: (value: ExporterProfileList) => void = () => {};
    vi.mocked(searchExporterProfiles).mockImplementation((params: ExporterSearchParams) =>
      params.name
        ? new Promise((resolve) => {
            answerSearch = resolve;
          })
        : Promise.resolve(list(company('stray', null))),
    );
    renderSelect();
    const field = screen.getByRole('combobox', { name: 'Seller' });
    fireEvent.focus(field);
    // Let the not-yet-searching request answer first, as it does in the app.
    await waitFor(() => expect(searchExporterProfiles).toHaveBeenCalledWith({ limit: 1 }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    fireEvent.change(field, { target: { value: 'Acme' } });
    expect(screen.queryByRole('option')).not.toBeInTheDocument();
    expect(screen.queryByText('Unnamed company')).not.toBeInTheDocument();

    answerSearch(list(company('acme', 'Acme Exports')));
    expect(await screen.findByRole('option', { name: /Acme Exports/ })).toBeInTheDocument();
    expect(screen.queryByText('Unnamed company')).not.toBeInTheDocument();
  });

  it('chooses with the keyboard, then shows the name with a way to clear it', async () => {
    vi.mocked(searchExporterProfiles).mockImplementation((params: ExporterSearchParams) =>
      Promise.resolve(params.name ? list(company('a', 'Acme Exports'), company('b', 'Acme Foods')) : list()),
    );
    const onChange = renderSelect();
    const field = screen.getByRole('combobox', { name: 'Seller' });
    fireEvent.change(field, { target: { value: 'Acme' } });
    await screen.findByRole('option', { name: /Acme Foods/ });

    fireEvent.keyDown(field, { key: 'ArrowDown' });
    fireEvent.keyDown(field, { key: 'Enter' });
    expect(onChange).toHaveBeenLastCalledWith('b');
    expect(screen.getByTestId('company-select-value')).toHaveTextContent('Acme Foods');

    fireEvent.click(screen.getByRole('button', { name: 'Clear seller' }));
    expect(onChange).toHaveBeenLastCalledWith(null);
    expect(screen.getByRole('combobox', { name: 'Seller' })).toBeInTheDocument();
  });
});
