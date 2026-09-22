import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation } from 'react-router-dom';
import { z } from 'zod';

import { ApiError } from '@/lib/api/errors';
import { useAuth } from '@/platform/auth';

const loginSchema = z.object({
  email: z
    .string()
    .min(1, 'Email is required')
    .email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
});

type LoginFormValues = z.infer<typeof loginSchema>;

export function LoginPage() {
  const { status, login } = useAuth();
  const location = useLocation();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) });

  if (status === 'authenticated') {
    const redirectTo =
      (location.state as { from?: string } | null)?.from ?? '/';
    return <Navigate to={redirectTo} replace />;
  }

  const onSubmit = async (values: LoginFormValues) => {
    setServerError(null);
    try {
      await login(values.email, values.password);
    } catch (error) {
      setServerError(
        error instanceof ApiError
          ? error.message
          : 'Unable to sign in. Please try again.',
      );
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-subtle px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-lg bg-ink text-lg font-semibold text-brand-400">
            A
          </div>
          <h1 className="text-lg font-semibold text-ink">Sign in to ANER</h1>
          <p className="mt-1 text-sm text-ink-muted">Exporter CRM</p>
        </div>

        <form
          onSubmit={(event) => void handleSubmit(onSubmit)(event)}
          className="rounded-lg border border-border bg-surface p-6 shadow-card"
          noValidate
        >
          {serverError && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-status-failed/30 bg-red-50 px-3 py-2 text-sm text-status-failed"
            >
              {serverError}
            </div>
          )}

          <label
            htmlFor="email"
            className="mb-1 block text-sm font-medium text-ink"
          >
            Email
          </label>
          <input
            id="email"
            type="email"
            autoComplete="email"
            className="mb-1 w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            {...register('email')}
          />
          {errors.email && (
            <p className="mb-3 text-xs text-status-failed">
              {errors.email.message}
            </p>
          )}
          {!errors.email && <div className="mb-3" />}

          <label
            htmlFor="password"
            className="mb-1 block text-sm font-medium text-ink"
          >
            Password
          </label>
          <input
            id="password"
            type="password"
            autoComplete="current-password"
            className="mb-1 w-full rounded-lg border border-border px-3 py-2 text-sm text-ink outline-none focus:border-brand-500 focus:ring-1 focus:ring-brand-500"
            {...register('password')}
          />
          {errors.password && (
            <p className="mb-3 text-xs text-status-failed">
              {errors.password.message}
            </p>
          )}
          {!errors.password && <div className="mb-3" />}

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-2 w-full rounded-lg bg-ink px-3 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {isSubmitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
