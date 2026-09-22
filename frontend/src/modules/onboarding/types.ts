import type { components } from '@/lib/api/schema';

// Thin aliases onto the generated OpenAPI schema — see lib/api/types.ts's
// module docstring for why: a backend reshape becomes a compile error at
// the actual use site, never a silent runtime mismatch.
export type ExporterProfileListItem =
  components['schemas']['ExporterProfileListItemResponse'];
export type ExporterProfileDetail =
  components['schemas']['ExporterProfileDetailResponse'];
export type ExporterProfile = components['schemas']['ExporterProfileResponse'];
export type CreateExporterLeadRequest =
  components['schemas']['CreateExporterProfileRequest'];
export type ExporterLifecycleStatus =
  components['schemas']['ExporterLifecycleStatus'];
export type ExporterSource = components['schemas']['ExporterSource'];
export type ExporterContact = components['schemas']['ExporterContactResponse'];
export type AddExporterContactRequest =
  components['schemas']['AddExporterContactRequest'];
export type ExporterActivity =
  components['schemas']['ExporterActivityResponse'];
export type ExporterActivityType = components['schemas']['ExporterActivityType'];
export type LogExporterActivityRequest =
  components['schemas']['LogExporterActivityRequest'];

export interface ExporterSearchParams {
  legalName?: string;
  gstin?: string;
  pan?: string;
  iec?: string;
  source?: ExporterSource;
  status?: ExporterLifecycleStatus;
  limit?: number;
  offset?: number;
}
export type VerificationResult =
  components['schemas']['VerificationResultResponse'];
export type VerificationResultList =
  components['schemas']['VerificationResultListResponse'];
export type VerificationType = components['schemas']['VerificationType'];
export type VerificationEntityType =
  components['schemas']['VerificationEntityType'];
export type VerificationReviewStatus =
  components['schemas']['VerificationReviewStatus'];
export type TriggerVerificationRequest = Omit<
  components['schemas']['TriggerVerificationRequest'],
  'payload'
> & { payload?: Record<string, unknown> };
export type RecordVerificationReviewRequest =
  components['schemas']['RecordReviewRequest'];

export type ScreeningChecklistStatus =
  | 'NEEDS_REVIEW'
  | 'PASSED'
  | 'FAILED'
  | 'EXEMPT';

export interface ScreeningReviewItem {
  id: string;
  customer_id: string;
  item_key: string;
  status: ScreeningChecklistStatus;
  comment: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ScreeningReviewList {
  customer_id: string;
  items: ScreeningReviewItem[];
}

export interface BankActivityFinding {
  id: string;
  customer_id: string;
  provider: string;
  finding_type: string;
  title: string;
  description: string | null;
  risk_level: string;
  status: string;
  provider_reference: string | null;
  detected_at: string;
  created_at: string;
}

export interface BankActivityResponse {
  customer_id: string;
  connected_accounts: number;
  last_synced_at: string | null;
  open_findings: number;
  findings: BankActivityFinding[];
}
