import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { Navigate, useLocation } from 'react-router-dom';
import { z } from 'zod';

import { Button, Field, FormError, Input } from '@/components';
import { BrandMark } from '@/design/BrandMark';
import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { useAuth } from '@/platform/auth';

import { SignInScene } from './SignInScene';

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
    // §8.1: the form on the left, and on wide screens a panel on the right with the
    // moving picture and what the product does. Always light. On wide screens the
    // page is exactly the window's height: the picture shrinks to the room left, so
    // the page never scrolls.
    <div
      data-theme="light"
      className="grid min-h-dvh bg-surface lg:h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]"
    >
      <div className="flex min-h-0 flex-col overflow-y-auto px-6 py-6 sm:px-10">
        <BrandMark mark />

        <main className="flex flex-1 items-center justify-center py-8">
          <div className="w-full max-w-[25rem]">
            <h1 className="text-title font-semibold text-ink">Sign in to Exporter CRM</h1>
            <p className="mt-1 text-body text-ink-3">Use your work email and password.</p>

            <form
              onSubmit={(event) => void handleSubmit(onSubmit)(event)}
              className="mt-8 space-y-4"
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

            <p className="mt-6 text-secondary text-ink-3">
              No account yet, or locked out? Ask an administrator.
            </p>
          </div>
        </main>

        <p className="text-caption text-ink-4">© {new Date().getFullYear()} Aner Labs</p>
      </div>

      <aside
        aria-label="About Exporter CRM"
        className="m-3 hidden min-h-0 flex-col items-center justify-center overflow-hidden rounded-xl bg-accent-tint px-10 py-8 lg:flex"
      >
        <SignInScene className="min-h-0 w-full max-w-[26rem] flex-1 [max-height:26rem]" />

        <h2 className="mt-6 max-w-[28rem] text-balance text-center text-[1.5rem] font-semibold leading-8 text-ink">
          Every exporter, from first call to handover
        </h2>

        <ul className="mt-6 w-full max-w-[28rem] space-y-4">
          {FEATURES.map(({ icon: FeatureIcon, title, detail }) => (
            <li key={title} className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded bg-surface text-accent">
                <FeatureIcon size={20} aria-hidden />
              </span>
              <span>
                <span className="block text-body font-semibold text-ink">{title}</span>
                <span className="block text-secondary text-ink-3">{detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}

const FEATURES = [
  {
    icon: Icon.backgroundCheck,
    title: 'Companies and background checks',
    detail: 'One record per exporter, with its checks and documents.',
  },
  {
    icon: Icon.pipeline,
    title: 'Deal pipeline',
    detail: 'Every deal and its next step, stage by stage.',
  },
  {
    icon: Icon.trade,
    title: 'Approvals and handover',
    detail: 'Compliance signs off before a deal is handed over.',
  },
];
