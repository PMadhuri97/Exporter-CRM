import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation } from 'react-router-dom';
import { z } from 'zod';

import { Button, Field, FormError, Input } from '@/components';
import { ApiError } from '@/lib/api/errors';
import { useAuth } from '@/platform/auth';

const loginSchema = z.object({
  email: z.string().min(1, 'Email is required').email('Enter a valid email address'),
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
    const redirectTo = (location.state as { from?: string } | null)?.from ?? '/';
    return <Navigate to={redirectTo} replace />;
  }

  const onSubmit = async (values: LoginFormValues) => {
    setServerError(null);
    try {
      await login(values.email, values.password);
    } catch (error) {
      setServerError(
        error instanceof ApiError ? error.message : 'Unable to sign in. Please try again.',
      );
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-surface-subtle px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <div className="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-brand-600 text-lg font-bold text-white dark:text-surface">
            A
          </div>
          <h1 className="text-xl font-semibold tracking-tight text-ink">Sign in to ANER</h1>
          <p className="mt-1 text-sm text-ink-muted">Exporter CRM</p>
        </div>

        <form
          onSubmit={(event) => void handleSubmit(onSubmit)(event)}
          className="space-y-4 rounded-xl border border-border bg-surface p-6 shadow-card"
          noValidate
        >
          <FormError>{serverError}</FormError>

          <Field label="Email" htmlFor="email" error={errors.email?.message}>
            <Input id="email" type="email" autoComplete="email" {...register('email')} />
          </Field>

          <Field label="Password" htmlFor="password" error={errors.password?.message}>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              {...register('password')}
            />
          </Field>

          <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>
            Sign in
          </Button>
        </form>
      </div>
    </div>
  );
}
