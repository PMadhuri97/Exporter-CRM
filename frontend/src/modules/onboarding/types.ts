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

// ── Document requirements (B2) ───────────────────────────────────────────────
//
// Hand-written rather than aliased onto `components['schemas'][...]`, matching
// the precedent `ScreeningReviewItem`/`BankActivityFinding` set above: two
// other routers land in this phase, and `schema.ts` is regenerated once all
// three have merged. Point these at the generated schema in that pass.

export interface DocumentRequirement {
  document_type: string;
  /** `null` means the document is accepted regardless of age. */
  max_age_days: number | null;
  validity_description: string | null;
}

export interface DocumentRequirementsResponse {
  entity_type: string;
  registration_country: string;
  sector_code: string | null;
  corridor_intent: string | null;
  declared_monthly_volume_usd: number | null;
  policy_version: string;
  required_documents: DocumentRequirement[];
  total: number;
}

/**
 * The profile the policy is evaluated against. `entity_type` and
 * `registration_country` are required by the endpoint; the rest are genuinely
 * optional signals that only some conditional rules test.
 */
export interface DocumentRequirementsParams {
  entityType: string;
  registrationCountry: string;
  sectorCode?: string;
  corridorIntent?: string;
  declaredMonthlyVolumeUsd?: number;
}

// ── Risk rating check (B3) ───────────────────────────────────────────────────

/**
 * The payload `RiskRatingAdapter` reads, under the same key names the backend's
 * `RiskRatingService.calculate` uses. The adapter rejects an unknown key, so
 * this type is the contract, not a hint.
 */
export interface RiskRatingPayload {
  entity_type: string;
  registration_country: string;
  sector_code?: string | null;
  declared_monthly_volume_usd?: number | null;
  ubo_count?: number | null;
  ubo_pep_statuses?: string[] | null;
  screening_result?: string | null;
  kyb_discrepancies?: string[] | null;
}

/**
 * `normalized_result` on a RISK_RATING result — the same JSON
 * `onboarding_request.risk_rating_factors` stores, so the two read alike.
 */
export interface RiskRatingFactors {
  score: number;
  risk_rating: string;
  factors: { factor: string; value: unknown; score: number; detail: string }[];
  edd_required: boolean;
  edd_reason: string | null;
  config_version: string;
}
