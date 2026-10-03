import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { matchCompany, searchExporterProfiles } from '../api';
import type { CompanyMatch, CompanyMatchCandidate, ExporterProfileListItem } from '../types';

import { CompanyPicker } from './CompanyPicker';

vi.mock('../api', () => ({
  searchExporterProfiles: vi.fn(),
  matchCompany: vi.fn(),
}));

const ROTTERDAM = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const ANTWERP = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const SELLER = 'ssssssss-ssss-4sss-8sss-ssssssssssss';

function company(overrides: Partial<ExporterProfileListItem> = {}): ExporterProfileListItem {
  return {
    customer_id: ROTTERDAM,
    name: 'Rotterdam Trading BV',
    country: 'NL',
    journey: 'LEAD',
    pipeline_status: 'IN_PIPELINE',
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- test double
    ...(overrides as any),
  } as ExporterProfileListItem;
}

function candidate(overrides: Partial<CompanyMatchCandidate> = {}): CompanyMatchCandidate {
  return {
    company_id: ROTTERDAM,
    name: 'Rotterdam Trading BV',
    country: 'NL',
    pipeline_status: 'IN_PIPELINE',
    ...overrides,
  };
}

function matchResult(overrides: Partial<CompanyMatch> = {}): CompanyMatch {
  return {
    kind: 'NEW',
    company_id: null,
    reason: null,
    needs_a_person: false,
    candidates: [],
    ...overrides,
  } as CompanyMatch;
}

function renderPicker(onSelect = vi.fn(), excludeCompanyId?: string, country?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompanyPicker
        onSelect={onSelect}
        excludeCompanyId={excludeCompanyId}
        country={country}
      />
    </QueryClientProvider>,
  );
  return onSelect;
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(searchExporterProfiles).mockResolvedValue({
    profiles: [company()],
    limit: 10,
    offset: 0,
  });
  vi.mocked(matchCompany).mockResolvedValue(matchResult());
});

describe('CompanyPicker — searching by name', () => {
  it('does not search until the term is worth a query', async () => {
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), { target: { value: 'R' } });
    expect(await screen.findByText(/at least two characters/)).toBeInTheDocument();
    // One letter would return most of the database and tell the user nothing.
    await waitFor(() =>
      expect(
        vi
          .mocked(searchExporterProfiles)
          .mock.calls.every(([params]) => params?.name === undefined),
      ).toBe(true),
    );
  });

  it('lists matches and hands back the company id when one is picked', async () => {
    const onSelect = renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'Rotterdam' },
    });

    fireEvent.click(await screen.findByRole('button', { name: /Rotterdam Trading BV/ }));
    expect(onSelect).toHaveBeenCalledWith(ROTTERDAM);
  });

  it('leaves the seller out, so nobody picks a company as its own buyer', async () => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [company(), company({ customer_id: SELLER, name: 'Acme Exports' })],
      limit: 10,
      offset: 0,
    });
    renderPicker(vi.fn(), SELLER);

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'company' },
    });

    expect(await screen.findByText('Rotterdam Trading BV')).toBeInTheDocument();
    // `ck_deal_buyer_is_not_the_seller` would refuse it anyway; offering the choice
    // and then failing is worse than not offering it.
    expect(screen.queryByText('Acme Exports')).not.toBeInTheDocument();
  });

  it('marks a buyer-only company rather than showing its journey', async () => {
    // Its journey column reads LEAD because the column is NOT NULL, which would be
    // actively misleading here: nobody is selling to it.
    vi.mocked(searchExporterProfiles).mockResolvedValue({
      profiles: [company({ pipeline_status: 'NOT_IN_PIPELINE' })],
      limit: 10,
      offset: 0,
    });
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'Rotterdam' },
    });

    expect(await screen.findByText(/Not in pipeline/)).toBeInTheDocument();
    expect(screen.queryByText(/LEAD/)).not.toBeInTheDocument();
  });
});

describe('CompanyPicker — searching by identifier', () => {
  it('sends the whole identifier and the country, and never displays it back', async () => {
    vi.mocked(matchCompany).mockResolvedValue(
      matchResult({ kind: 'MATCHED', company_id: ROTTERDAM, candidates: [candidate()] }),
    );
    const onSelect = renderPicker(vi.fn(), undefined, 'NL');

    fireEvent.change(screen.getByLabelText('PAN'), { target: { value: 'ABCDE1234F' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    await waitFor(() => expect(vi.mocked(matchCompany)).toHaveBeenCalled());
    expect(vi.mocked(matchCompany).mock.calls[0]?.[0]).toMatchObject({
      pan: 'ABCDE1234F',
      country: 'NL',
    });

    fireEvent.click(await screen.findByRole('button', { name: /Rotterdam Trading BV/ }));
    expect(onSelect).toHaveBeenCalledWith(ROTTERDAM);
  });

  it('can look a company up by GSTIN or registration number instead', async () => {
    renderPicker();

    fireEvent.click(screen.getByRole('button', { name: 'GSTIN' }));
    fireEvent.change(screen.getByLabelText('GSTIN'), {
      target: { value: '27ABCDE1234F1Z5' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    await waitFor(() => expect(vi.mocked(matchCompany)).toHaveBeenCalled());
    expect(vi.mocked(matchCompany).mock.calls[0]?.[0]).toMatchObject({
      gstin: '27ABCDE1234F1Z5',
    });
  });

  it('says plainly that a partial value will not do', () => {
    renderPicker();
    expect(screen.getByText(/Partial values are not accepted/)).toBeInTheDocument();
    // And that the value does not come back — BQ-2 lets an identifier *name* a
    // company while the identifiers themselves stay masked.
    expect(screen.getByText(/never shown back to you/)).toBeInTheDocument();
  });

  it('shows the server refusal rather than guessing the rule', async () => {
    vi.mocked(matchCompany).mockRejectedValue(new Error('422'));
    renderPicker();

    fireEvent.change(screen.getByLabelText('PAN'), { target: { value: 'ABCDE' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    expect(await screen.findByText(/was refused/)).toBeInTheDocument();
  });
});

describe('CompanyPicker — the four answers', () => {
  it('warns on CONFLICT and preselects nothing', async () => {
    vi.mocked(matchCompany).mockResolvedValue(
      matchResult({
        kind: 'CONFLICT',
        needs_a_person: true,
        reason: 'these identifiers name more than one company on file: GSTIN → 2',
        candidates: [candidate(), candidate({ company_id: ANTWERP, name: 'Antwerp Shipping NV' })],
      }),
    );
    const onSelect = renderPicker();

    fireEvent.change(screen.getByLabelText('PAN'), { target: { value: 'ABCDE1234F' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/more than one company/);
    // Both named, nothing chosen: picking one is how a deal gets attached to the
    // wrong company (IQ-8).
    expect(await screen.findByText('Antwerp Shipping NV')).toBeInTheDocument();
    expect(onSelect).not.toHaveBeenCalled();
  });

  it('asks the user to check a POSSIBLE_DUPLICATE first', async () => {
    vi.mocked(matchCompany).mockResolvedValue(
      matchResult({
        kind: 'POSSIBLE_DUPLICATE',
        needs_a_person: true,
        reason: '1 company in NL already named this, ignoring punctuation and legal form',
        candidates: [candidate()],
      }),
    );
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'Rotterdam Trading' },
    });
    fireEvent.blur(screen.getByPlaceholderText('Company name'));

    expect(await screen.findByText(/Check these first/)).toBeInTheDocument();
    expect(await screen.findByText(/already named this/)).toBeInTheDocument();
  });

  it('marks a candidate that exists only as a buyer', async () => {
    vi.mocked(matchCompany).mockResolvedValue(
      matchResult({
        kind: 'MATCHED',
        company_id: ROTTERDAM,
        candidates: [candidate({ pipeline_status: 'NOT_IN_PIPELINE' })],
      }),
    );
    renderPicker();

    fireEvent.change(screen.getByLabelText('PAN'), { target: { value: 'ABCDE1234F' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    // Usually exactly the record the RM wants, so it says so rather than looking
    // like a half-built company.
    expect(await screen.findByText(/exists as a buyer/)).toBeInTheDocument();
  });

  it('says where creating a company lives, rather than offering a button that misfiles it', async () => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 10, offset: 0 });
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'nobody' },
    });

    // A create button here that made an ordinary IN_PIPELINE lead would inflate the
    // sales pipeline — the exact failure P4-2 exists to prevent.
    expect(await screen.findByText(/Creating a buyer company from here arrives/)).toBeInTheDocument();
  });
});
