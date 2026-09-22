import { QueryClient } from '@tanstack/react-query';

import { ApiError } from './api/errors';

// A 401 that survives `apiClient.ts`'s own refresh-and-retry means the
// session is genuinely gone — retrying it against Query's default backoff
// would just repeat the same failure. Everything else gets Query's normal
// retry behavior.
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status === 401) return false;
        return failureCount < 2;
      },
      staleTime: 30_000,
    },
  },
});
