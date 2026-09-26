import type { components } from '@/lib/api/schema';

// Thin aliases onto the generated OpenAPI schema — see lib/api/types.ts's
// module docstring for why: a backend reshape becomes a compile error at
// the actual use site, never a silent runtime mismatch.
type Schemas = components['schemas'];

export type ExporterProfileListItem = Schemas['ExporterProfileListItemResponse'];
export type ExporterProfileDetail = Schemas['ExporterProfileDetailResponse'];
export type ExporterProfile = Schemas['ExporterProfileResponse'];
export type CreateExporterLeadRequest = Schemas['CreateExporterProfileRequest'];
export type UpdateExporterProfileRequest = Schemas['UpdateExporterProfileRequest'];
export type SetMarkerRequest = Schemas['SetMarkerRequest'];
export type MarkerMove = Schemas['MarkerMoveResponse'];
export type DuplicateGstinWarning = Schemas['DuplicateGstinWarningResponse'];
export type ExporterSource = Schemas['ExporterSource'];
/** The journey: LEAD -> PROSPECT -> CUSTOMER. Never moved by hand. */
export type ExporterJourney = Schemas['ExporterJourney'];
/** The qualification gauge, beside the journey — not a journey stage. */
export type QualificationState = Schemas['QualificationState'];
/** A commercial pause or ending, beside the journey — not a journey stage. */
export type ExporterMarker = Schemas['ExporterMarker'];
export type ExporterContact = Schemas['ExporterContactResponse'];
export type AddExporterContactRequest = Schemas['AddExporterContactRequest'];
export type ExporterActivity = Schemas['ExporterActivityResponse'];
export type ExporterActivityType = Schemas['ExporterActivityType'];
export type LogExporterActivityRequest = Schemas['LogExporterActivityRequest'];

// ── Qualification ──
export type Qualification = Schemas['QualificationResponse'];
export type QualificationOutcomeValue = Schemas['QualificationOutcomeValue'];
export type CriterionResultValue = Schemas['CriterionResultValue'];
export type RecordResultsRequest = Schemas['RecordResultsRequest'];
export type RecordOutcomeRequest = Schemas['RecordOutcomeRequest'];
export type ReasonCode = Schemas['ReasonCodeResponse'];

// ── Company intake ──
export type IntakeResult = Schemas['IntakeResponse'];
export type ImportReport = Schemas['ImportReportResponse'];
export type ImportRow = Schemas['ImportRowResponse'];

export interface ExporterSearchParams {
  name?: string;
  gstin?: string;
  pan?: string;
  iec?: string;
  source?: ExporterSource;
  journey?: ExporterJourney;
  qualification?: QualificationState;
  marker?: ExporterMarker;
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
