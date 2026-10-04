import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Toaster } from 'sonner';

// Self-hosted type (§5.3): the serif is display-only, so only its regular and
// italic load; the sans and mono are variable. Each file covers its subsets by
// `unicode-range`, so a browser fetches latin-ext only for a name that needs it.
import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';
import '@fontsource-variable/instrument-sans/wght.css';
import '@fontsource-variable/jetbrains-mono/wght.css';

import { queryClient } from '@/lib/queryClient';
import { AuthProvider } from '@/platform/auth';
import { AppRouter } from '@/routes/AppRouter';

import './design/tokens.css';
import './index.css';

const rootElement = document.getElementById('root');
if (rootElement === null) throw new Error('#root element not found');

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppRouter />
        {/* Restyled to the tokens in index.css — no `richColors`: a toast is ink on
            raised paper, and only its icon carries the meaning's colour. */}
        <Toaster closeButton position="top-right" />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
