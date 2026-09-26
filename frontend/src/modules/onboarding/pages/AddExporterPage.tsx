import { zodResolver } from '@hookform/resolvers/zod';
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { z } from 'zod';

import { ApiError } from '@/lib/api/errors';

import { useCreateExporterLead } from '../hooks';

// Limited to CreateExporterProfileRequest's real fields (EXP-F3's own
// scoping rule: no Country/Sector/Consent/Buyers fields — see
// docs/exporter-crm-frontend-tickets.md's backend-gaps list). Trimmed
// further than the backend allows for a leaner first form:
// export_markets/products/year_established are all nullable server-side and
// left off here — easy to add once there's a reason to.
const addExporterSchema = z.object({
  // The company's identity (docs/contracts/company-record.md §2.1). The
  // person adding the company is never asked for their own contact — the
  // backend takes it from the signed-in session.
  name: z.string().trim().min(1, 'Company name is required').max(255),
  country: z
    .string()
    .trim()
    .regex(/^[A-Za-z]{2}$/, 'Use a 2-letter country code (e.g. IN, US)')
    .transform((v) => v.toUpperCase()),
  source: z.enum([
    'MANUAL',
    'SALES',
    'REFERRAL',
    'RXIL',
    'PARTNER',
    'API',
    'BROKER',
    'EVENT',
    'EXISTING_CUSTOMER',
  ]),
  relationship_manager: z.string().max(255).optional().or(z.literal('')),
  gstin: z.string().max(15).optional().or(z.literal('')),
  pan: z.string().max(10).optional().or(z.literal('')),
  iec: z.string().max(10).optional().or(z.literal('')),
  industry: z.string().max(255).optional().or(z.literal('')),
  website: z.string().max(2048).optional().or(z.literal('')),
});

type AddExporterFormValues = z.infer<typeof addExporterSchema>;

const SOURCE_LABEL: Record<AddExporterFormValues['source'], string> = {
  MANUAL: 'Manual entry',
  SALES: 'Sales',
  REFERRAL: 'Referral',
  RXIL: 'RXIL',
  PARTNER: 'Partner',
  API: 'API',
  BROKER: 'Broker',
  EVENT: 'Event',
  EXISTING_CUSTOMER: 'Existing customer',
};

function emptyToUndefined(value: string | undefined): string | undefined {
  return value === '' ? undefined : value;
}

export function AddExporterPage() {
  const navigate = useNavigate();
  const createLead = useCreateExporterLead();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<AddExporterFormValues>({
    resolver: zodResolver(addExporterSchema),
    defaultValues: { source: 'MANUAL' },
  });

  const onSubmit = async (values: AddExporterFormValues) => {
    setServerError(null);
    try {
      const profile = await createLead.mutateAsync({
        name: values.name,
        country: values.country,
        source: values.source,
        // The backend defaults this to LEAD when omitted, but the generated
        // type still marks it required — passed explicitly rather than
        // fighting the generator over a field this form never lets the user
        // change anyway (a brand-new Lead always starts at LEAD).
        lifecycle_status: 'LEAD',
        relationship_manager: emptyToUndefined(values.relationship_manager),
        // One GSTIN from the form; a company may hold several (one per state).
        gstins: values.gstin ? [values.gstin] : undefined,
        pan: emptyToUndefined(values.pan),
        iec: emptyToUndefined(values.iec),
        industry: emptyToUndefined(values.industry),
        website: emptyToUndefined(values.website),
      });
      navigate(`/exporters/${profile.customer_id}`);
    } catch (error) {
      setServerError(
        error instanceof ApiError
          ? error.message
          : 'Unable to create this exporter. Try again.',
      );
    }
  };

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="text-lg font-semibold text-ink">Add Exporter</h1>
      <p className="mt-1 text-sm text-ink-muted">
        Capture exporter details and consent.
      </p>

      <form
        onSubmit={(e) => void handleSubmit(onSubmit)(e)}
        noValidate
        className="mt-6 space-y-4 rounded-lg border border-border bg-surface p-6 shadow-card"
      >
        {serverError && (
          <div
            role="alert"
            className="rounded-lg border border-status-failed/30 bg-red-50 px-3 py-2 text-sm text-status-failed"
          >
            {serverError}
          </div>
        )}

        <Field label="Company Name" error={errors.name?.message} required>
          <input
            className="input"
            placeholder="e.g. Acme Exports Pvt Ltd"
            {...register('name')}
          />
        </Field>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Country" error={errors.country?.message} required>
            <input
              className="input uppercase"
              placeholder="IN"
              maxLength={2}
              {...register('country')}
            />
          </Field>
          <Field label="Source" error={errors.source?.message} required>
            <select className="input" {...register('source')}>
              {Object.entries(SOURCE_LABEL).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
        </div>

        <Field
          label="Relationship Manager"
          error={errors.relationship_manager?.message}
        >
          <input className="input" {...register('relationship_manager')} />
        </Field>

        <div className="grid grid-cols-3 gap-4">
          <Field label="PAN" error={errors.pan?.message}>
            <input
              className="input"
              placeholder="e.g. ABCDE1234F"
              {...register('pan')}
            />
          </Field>
          <Field label="GSTIN" error={errors.gstin?.message}>
            <input
              className="input"
              placeholder="e.g. 27ABCDE1234F1Z5"
              {...register('gstin')}
            />
          </Field>
          <Field label="IEC" error={errors.iec?.message}>
            <input className="input" {...register('iec')} />
          </Field>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <Field label="Industry" error={errors.industry?.message}>
            <input className="input" {...register('industry')} />
          </Field>
          <Field label="Website" error={errors.website?.message}>
            <input
              className="input"
              placeholder="https://…"
              {...register('website')}
            />
          </Field>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={() => navigate('/exporters')}
            className="rounded-lg px-3 py-2 text-sm font-medium text-ink-muted hover:bg-surface-sunken"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={isSubmitting}
            className="rounded-lg bg-ink px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {isSubmitting ? 'Creating…' : 'Create Exporter'}
          </button>
        </div>
      </form>
    </div>
  );
}

interface FieldProps {
  label: string;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
}

function Field({ label, error, required, children }: FieldProps) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-ink">
        {label}
        {required && <span className="text-status-failed"> *</span>}
      </span>
      {children}
      {error && (
        <span className="mt-1 block text-xs text-status-failed">{error}</span>
      )}
    </label>
  );
}
