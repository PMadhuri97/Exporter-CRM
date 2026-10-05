import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ApiError } from '@/lib/api/errors';

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
    // And that the value does not come back — an identifier may *name* a
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
    // wrong company.
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

  it('creates nothing unless its caller supplies the buyer-company path', async () => {
    // A create button that made an ordinary IN_PIPELINE lead would inflate the sales
    // pipeline — the exact failure to prevent. So without `onCreate`
    // (the deal's buyer route) there is no button at all.
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 10, offset: 0 });
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    renderPicker();

    fireEvent.change(screen.getByPlaceholderText('Company name'), {
      target: { value: 'nobody' },
    });
    fireEvent.blur(screen.getByPlaceholderText('Company name'));

    expect(await screen.findByText(/No company on file matches/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create buyer company' })).not.toBeInTheDocument();
  });
});

// ── Creating the buyer as a company outside the pipeline ─────────────────────

function renderWithCreate(
  onCreate = vi.fn().mockResolvedValue(undefined),
  { onSelect = vi.fn(), country }: { onSelect?: (companyId: string) => void; country?: string } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CompanyPicker onSelect={onSelect} onCreate={onCreate} country={country} />
    </QueryClientProvider>,
  );
  return { onCreate, onSelect };
}

async function searchByName(name: string) {
  fireEvent.change(screen.getByPlaceholderText('Company name'), { target: { value: name } });
  fireEvent.blur(screen.getByPlaceholderText('Company name'));
}

describe('CompanyPicker — creating a buyer company', () => {
  beforeEach(() => {
    vi.mocked(searchExporterProfiles).mockResolvedValue({ profiles: [], limit: 10, offset: 0 });
  });

  it('looks the name up on Enter, not only when the field loses focus', async () => {
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    renderWithCreate();

    const field = screen.getByPlaceholderText('Company name');
    fireEvent.change(field, { target: { value: 'Elbe Garn Handels GmbH' } });
    expect(await screen.findByText(/Press Enter to look the name up/)).toBeInTheDocument();
    fireEvent.keyDown(field, { key: 'Enter' });

    expect(await screen.findByRole('button', { name: 'Create buyer company' })).toBeInTheDocument();
    expect(matchCompany).toHaveBeenCalledTimes(1);
    expect(vi.mocked(matchCompany).mock.calls[0]?.[0]).toMatchObject({
      name: 'Elbe Garn Handels GmbH',
    });
  });

  it('offers it when the server answers NEW, and sends what the form holds', async () => {
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    const { onCreate } = renderWithCreate(undefined, { country: 'NL' });
    await searchByName('Brand New Buyer BV');

    fireEvent.click(await screen.findByRole('button', { name: 'Create buyer company' }));
    expect(screen.getByLabelText(/Company name/)).toHaveValue('Brand New Buyer BV');
    expect(screen.getByLabelText(/Country/)).toHaveValue('NL');

    // A buyer outside India needs its registration number before it can be sent.
    const submit = screen.getByRole('button', { name: 'Create buyer company' });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/Registration number/), {
      target: { value: 'KVK-12345678' },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith({
        name: 'Brand New Buyer BV',
        country: 'NL',
        pan: null,
        gstin: null,
        registration_number: 'KVK-12345678',
      }),
    );
  });

  it('asks an Indian buyer for a PAN and GSTIN, not a registration number', async () => {
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    const { onCreate } = renderWithCreate();
    await searchByName('Chennai Spices');

    fireEvent.click(await screen.findByRole('button', { name: 'Create buyer company' }));
    const form = screen.getByRole('form', { name: 'Create buyer company' });
    expect(within(form).queryByLabelText(/Registration number/)).not.toBeInTheDocument();
    fireEvent.change(within(form).getByLabelText('PAN'), { target: { value: 'ABCDE1234F' } });
    fireEvent.click(within(form).getByRole('button', { name: 'Create buyer company' }));

    await waitFor(() =>
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({ country: 'IN', pan: 'ABCDE1234F', registration_number: null }),
      ),
    );
  });

  it('carries over an identifier the RM looked up and nobody holds', async () => {
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    renderWithCreate();
    fireEvent.change(screen.getByLabelText('PAN'), { target: { value: 'ABCDE1234F' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    fireEvent.click(await screen.findByRole('button', { name: 'Create buyer company' }));
    const form = screen.getByRole('form', { name: 'Create buyer company' });
    expect(within(form).getByLabelText('PAN')).toHaveValue('ABCDE1234F');
  });

  it('is never offered when an identifier names a company on file', async () => {
    vi.mocked(matchCompany).mockResolvedValue(
      matchResult({ kind: 'MATCHED', company_id: ROTTERDAM, candidates: [candidate()] }),
    );
    renderWithCreate();
    fireEvent.change(screen.getByLabelText('PAN'), { target: { value: 'ABCDE1234F' } });
    fireEvent.click(screen.getByRole('button', { name: 'Look up' }));

    expect(await screen.findByRole('button', { name: /Rotterdam Trading BV/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Create buyer company' })).not.toBeInTheDocument();
  });

  it('is offered after look-alikes only as "none of these is the buyer"', async () => {
    vi.mocked(matchCompany).mockResolvedValue(
      matchResult({ kind: 'POSSIBLE_DUPLICATE', needs_a_person: true, candidates: [candidate()] }),
    );
    renderWithCreate();
    await searchByName('Rotterdam Trading');

    expect(await screen.findByText(/None of these is the buyer/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Create buyer company' })).toBeInTheDocument();
  });

  it('offers the company on file when the server says it already holds the identifier', async () => {
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError(
        409,
        'A company on file already holds these identifiers, so a new buyer company is not created: choose the existing one',
        'BUYER_COMPANY_ALREADY_KNOWN',
        null,
        { match_kind: 'MATCHED', company_ids: [ANTWERP] },
      ),
    );
    const { onSelect } = renderWithCreate(onCreate, { country: 'BE' });
    await searchByName('Antwerp Shipping');
    fireEvent.click(await screen.findByRole('button', { name: 'Create buyer company' }));
    fireEvent.change(screen.getByLabelText(/Registration number/), { target: { value: 'BE-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create buyer company' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/already holds these identifiers/);
    fireEvent.click(screen.getByRole('button', { name: 'Use the company on file' }));
    expect(onSelect).toHaveBeenCalledWith(ANTWERP);
  });

  it("shows the server's refusal in its own words", async () => {
    vi.mocked(matchCompany).mockResolvedValue(matchResult({ kind: 'NEW' }));
    const onCreate = vi.fn().mockRejectedValue(
      new ApiError(422, 'registration_number is required for a company outside India'),
    );
    renderWithCreate(onCreate, { country: 'DE' });
    await searchByName('Hamburg Imports');
    fireEvent.click(await screen.findByRole('button', { name: 'Create buyer company' }));
    fireEvent.change(screen.getByLabelText(/Registration number/), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Create buyer company' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'registration_number is required for a company outside India',
    );
    expect(screen.queryByRole('button', { name: 'Use the company on file' })).not.toBeInTheDocument();
  });
});
