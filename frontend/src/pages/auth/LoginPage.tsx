import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation } from 'react-router-dom';
import { z } from 'zod';

import { Button, Field, FormError, Input } from '@/components';
import { BrandMark } from '@/design/BrandMark';
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
    <div className="grid min-h-screen bg-paper lg:grid-cols-2">
      {/* §8.1: one serif line over a faint drawing of the journey track. No
          illustration, no gradient, no "Welcome back!". */}
      <aside className="relative hidden flex-col justify-between overflow-hidden border-r border-line p-12 lg:flex">
        <BrandMark />
        <div className="relative z-10">
          <p className="font-display text-display-xl text-ink">Every company, one record.</p>
          <p className="mt-3 max-w-md text-lead text-ink-2">
            Find, qualify and talk to exporters; hand deals over when the paperwork and the checks
            are clear.
          </p>
        </div>
        <JourneyDrawing />
      </aside>

      <main className="flex items-center justify-center px-4 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8">
            <BrandMark className="mb-8 lg:hidden" />
            <h1 className="font-display text-display-lg text-ink">Sign in</h1>
            <p className="mt-1 text-body text-ink-2">to the Aner Labs exporter CRM</p>
          </div>

          <form onSubmit={(event) => void handleSubmit(onSubmit)(event)} className="space-y-4" noValidate>
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
      </main>
    </div>
  );
}

/**
 * Lead, prospect, customer as three nodes on a hairline track, drawn slowly once.
 * Decorative only: hidden from assistive tech, and still under reduced motion.
 */
function JourneyDrawing() {
  return (
    <svg
      aria-hidden
      viewBox="0 0 520 80"
      className="pointer-events-none w-full max-w-lg text-ink-4"
      fill="none"
      stroke="currentColor"
    >
      <path
        d="M20 40 H500"
        strokeWidth="1"
        strokeDasharray="480"
        strokeDashoffset="480"
        className="motion-safe:animate-[draw_2.4s_cubic-bezier(.2,.8,.2,1)_forwards] motion-reduce:[stroke-dashoffset:0]"
      />
      {[20, 260, 500].map((x, index) => (
        <circle
          key={x}
          cx={x}
          cy="40"
          r="7"
          strokeWidth="1.25"
          className={index === 0 ? 'fill-current' : 'fill-paper'}
        />
      ))}
    </svg>
  );
}
