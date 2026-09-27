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

// ══════════════════════════════════════════════════════════════════════════════
// Section 9.3 — anchor blocks for Developers 3A and 3B
//
// This file is Developer 1's (architecture §8.1). Three people add aliases to it
// — 3A in each of its two phases, and 3B — and one shared append point at the end
// of the file is one conflicting hunk every time. So the seam commit cuts the
// tail into owned blocks, and each owner adds aliases only inside its own.
//
// Every alias here is a thin name onto the generated OpenAPI schema, as above:
// nothing is hand-written, so a backend reshape is a compile error at the use
// site rather than a silent mismatch.
// ══════════════════════════════════════════════════════════════════════════════

// ── Conversation and follow-ups — owner: Developer 3A (L3-02 … L3-04) ──
// (3A appends here; 3B does not.)
// Cut into the two phase sub-anchors below — phase agreement §6.3.

// ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ──
/** How the sales conversation is going. One thing only — not the journey, not
 * qualification, not the background check. Any value may follow any other. */
export type ExporterConversation = Schemas['ExporterConversation'];
export type Conversation = Schemas['ConversationResponse'];
/** One move the server says this user may make, and what it needs. Never a
 * hand-copied table on the client (architecture §7.5). */
export type ConversationMove = Schemas['ConversationMoveResponse'];
export type SetConversationRequest = Schemas['SetConversationRequest'];
/** A page of the shared CRM history log, read with `?dimension=conversation`.
 * Developer 1 owns the route; these are the generated names for its shapes. */
export type HistoryEntry = Schemas['HistoryEntryResponse'];
export type HistoryList = Schemas['HistoryListResponse'];

// ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
/** One follow-up: an activity with a due date, plus its completion if it has one. */
export type FollowUp = Schemas['FollowUpResponse'];
/** OUTSTANDING / OVERDUE / DONE. Derived on the server from whether a completion
 * exists — there is no status column on an activity, and there must not be one. */
export type FollowUpState = Schemas['FollowUpState'];
export type FollowUpOutcome = Schemas['FollowUpOutcome'];
export type FollowUpCompletion = Schemas['FollowUpCompletionSummary'];
export type CompleteFollowUpRequest = Schemas['CompleteFollowUpRequest'];
/** A company parked at NOT_NOW, due to be picked up on its check-back date. Not a
 * follow-up and not completable: it is dealt with by moving the conversation gauge. */
export type CheckBack = Schemas['CheckBackResponse'];
export type FollowUpList = Schemas['FollowUpListResponse'];

export interface FollowUpListParams {
  state?: FollowUpState;
  customerId?: string;
  actorId?: string;
  includeCheckBacks?: boolean;
  limit?: number;
  offset?: number;
}

// ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
// (3B appends here; 3A does not.)
