import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Toaster } from 'sonner';

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
        {/* Restyled to the tokens in index.css — no `richColors`: a toast is a white
            card, and only its icon carries the meaning's colour. */}
        <Toaster closeButton position="top-right" />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
