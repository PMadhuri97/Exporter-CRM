/**
 * Company intake — **owner: Developer 2** (L2-12, L2-13): RXIL packages and
 * bulk CSV import. Validation, matching and every refusal are the server's;
 * these functions only carry the request and return its report.
 */

import { apiRequest } from '@/lib/api/client';

import type { ImportReport, IntakeResult } from '../types';

/** An RXIL package, as RXIL sent it. The format is provisional. */
export function submitRxilPackage(pkg: unknown): Promise<IntakeResult> {
  return apiRequest<IntakeResult>('/onboarding/rxil/company-intake', {
    method: 'POST',
    body: pkg,
  });
}

/** The import template, as the server defines it (CSV text). */
export function getCompanyImportTemplate(): Promise<string> {
  return apiRequest<string>('/onboarding/imports/companies/template');
}

export function importCompanies(file: File): Promise<ImportReport> {
  const form = new FormData();
  form.append('file', file);
  return apiRequest<ImportReport>('/onboarding/imports/companies', {
    method: 'POST',
    body: form,
  });
}
