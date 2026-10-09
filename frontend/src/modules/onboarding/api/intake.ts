/**
 * Company intake: RXIL packages and
 * bulk company import (CSV or Excel). Validation, matching and every refusal are the server's;
 * these functions only carry the request and return its report.
 */

import { apiRequest } from '@/lib/api/client';

import type { ImportPreview, ImportReport, IntakeResult } from '../types';

/** An RXIL package, as RXIL sent it. The format is provisional. */
export function submitRxilPackage(pkg: unknown): Promise<IntakeResult> {
  return apiRequest<IntakeResult>('/onboarding/rxil/company-intake', {
    method: 'POST',
    body: pkg,
  });
}

export type ImportTemplateFormat = 'xlsx' | 'csv';

/**
 * The import template, as the server defines it: an Excel workbook with an
 * Instructions sheet and dropdowns, or the CSV header row.
 */
export function getCompanyImportTemplate(format: ImportTemplateFormat): Promise<Blob> {
  return apiRequest<Blob>(`/onboarding/imports/companies/template?format=${format}`, {
    parseAs: 'blob',
  });
}

/** The file as the import would read it: columns, first rows, header problems. Saves nothing. */
export function previewCompanyImport(file: File): Promise<ImportPreview> {
  const form = new FormData();
  form.append('file', file);
  return apiRequest<ImportPreview>('/onboarding/imports/companies/preview', {
    method: 'POST',
    body: form,
  });
}

export function importCompanies(file: File): Promise<ImportReport> {
  const form = new FormData();
  form.append('file', file);
  return apiRequest<ImportReport>('/onboarding/imports/companies', {
    method: 'POST',
    body: form,
  });
}
