import { QueryClientProvider } from '@tanstack/react-query';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Toaster } from 'sonner';

import { queryClient } from '@/lib/queryClient';
import { AuthProvider } from '@/platform/auth';
import { AppRouter } from '@/routes/AppRouter';

import './index.css';

const rootElement = document.getElementById('root');
if (rootElement === null) throw new Error('#root element not found');

createRoot(rootElement).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <AppRouter />
        <Toaster richColors position="top-right" />
      </AuthProvider>
    </QueryClientProvider>
  </StrictMode>,
);
