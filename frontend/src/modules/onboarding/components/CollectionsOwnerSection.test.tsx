import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { useHasPermission } from '@/platform/access';

import { assignCollectionsOwner, listStaff } from '../api';

import { CollectionsOwnerSection } from './CollectionsOwnerSection';

vi.mock('@/platform/access', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/platform/access')>()),
  useHasPermission: vi.fn(),
}));
vi.mock('../api', () => ({ assignCollectionsOwner: vi.fn(), listStaff: vi.fn() }));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function renderSection(ownerId: string | null = null, ownerName: string | null = null) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <CollectionsOwnerSection customerId="c1" ownerId={ownerId} ownerName={ownerName} />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(listStaff).mockResolvedValue({
    staff: [
      { id: 'u1', name: 'Meera', role: 'OPERATIONS', companies: 3 },
      { id: 'u2', name: 'Arun', role: 'COMPLIANCE', companies: 0 },
    ],
  } as never);
  vi.mocked(assignCollectionsOwner).mockResolvedValue({} as never);
});

describe('CollectionsOwnerSection', () => {
  it('shows the owner to a reader who may not change it', () => {
    vi.mocked(useHasPermission).mockReturnValue(false);
    renderSection('u1', 'Meera');
    expect(screen.getByText('Meera')).toBeInTheDocument();
    expect(screen.queryByLabelText('Collections owner')).not.toBeInTheDocument();
  });

  it('names an owner, and asks why when changing one', async () => {
    vi.mocked(useHasPermission).mockReturnValue(true);
    renderSection('u1', 'Meera');
    await screen.findByRole('option', { name: 'Arun' });

    fireEvent.change(screen.getByLabelText('Collections owner'), { target: { value: 'u2' } });
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
    fireEvent.change(screen.getByLabelText(/^Why the change/), { target: { value: 'Moved team' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(assignCollectionsOwner).toHaveBeenCalledWith('c1', {
        user_id: 'u2',
        seen_user_id: 'u1',
        reason: 'Moved team',
      }),
    );
  });
});
