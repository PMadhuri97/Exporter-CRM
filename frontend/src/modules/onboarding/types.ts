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
  name?: string;
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

// The five types below were hand-written copies of shapes the backend already
// describes. Every one of them has a generated counterpart — they predate the
// screening/bank-activity responses landing in the OpenAPI document — and a
// hand-maintained copy of a generated type drifts silently: the backend
// renames a field, the interface here does not, and nothing fails until a
// value is undefined at runtime. They are aliases now, like everything above.
export type ScreeningReviewItem =
  components['schemas']['ScreeningReviewItemResponse'];
export type ScreeningReviewList =
  components['schemas']['ScreeningReviewListResponse'];
export type BankActivityFinding =
  components['schemas']['BankActivityFindingResponse'];
export type BankActivityResponse =
  components['schemas']['BankActivityResponse'];

/** The four checklist states, taken from the response rather than restated.
 *
 * Derived by indexing into the generated item type so adding a fifth state on
 * the server cannot leave this union behind. The backend declares them on
 * `ScreeningReviewItemResponse.status` and on
 * `UpdateScreeningReviewItemRequest.status`; this is the read side, which is
 * the one every caller here uses. */
export type ScreeningChecklistStatus = ScreeningReviewItem['status'];
