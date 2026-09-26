import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { submitRxilPackage } from '../api';

import { RxilIntakePage } from './RxilIntakePage';

vi.mock('../api', () => ({ submitRxilPackage: vi.fn() }));

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RxilIntakePage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function submit(text: string) {
  fireEvent.change(screen.getByLabelText('RXIL package'), { target: { value: text } });
  fireEvent.click(screen.getByRole('button', { name: 'Submit package' }));
}

describe('RxilIntakePage — RXIL company intake (L2-12, L2-14)', () => {
  beforeEach(() => {
    vi.mocked(submitRxilPackage).mockReset();
  });

  it('refuses text that is not JSON without calling the server', () => {
    renderPage();
    submit('not json');
    expect(screen.getByRole('alert')).toHaveTextContent('not valid JSON');
    expect(submitRxilPackage).not.toHaveBeenCalled();
  });

  it('sends the package as pasted and shows the result', async () => {
    vi.mocked(submitRxilPackage).mockResolvedValue({
      customer_id: '11111111-1111-4111-8111-111111111111',
      company: 'created',
      qualification: 'recorded',
      replayed: false,
      warnings: [],
    });
    renderPage();
    submit('{"package_id": "p-1", "company": {"name": "Acme"}}');
    await waitFor(() =>
      expect(submitRxilPackage).toHaveBeenCalledWith({
        package_id: 'p-1',
        company: { name: 'Acme' },
      }),
    );
    expect(await screen.findByText('Taken in')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open company' })).toHaveAttribute(
      'href',
      '/exporters/11111111-1111-4111-8111-111111111111',
    );
  });

  it('shows a refusal in the server’s own words', async () => {
    vi.mocked(submitRxilPackage).mockRejectedValue(
      new Error('Matches existing companies ambiguously'),
    );
    renderPage();
    submit('{"package_id": "p-2"}');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Matches existing companies ambiguously',
    );
  });
});
