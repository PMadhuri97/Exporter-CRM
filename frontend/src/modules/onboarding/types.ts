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
/** One version of a qualification criterion. Every change is a new version;
 * a version is never edited (L2-09). */
export type Criterion = Schemas['CriterionResponse'];
export type CriterionKind = Schemas['CriterionKind'];
export type ThresholdComparison = Schemas['ThresholdComparison'];
export type CreateCriterionRequest = Schemas['CreateCriterionRequest'];
export type CriterionDefinitionRequest = Schemas['CriterionDefinitionRequest'];

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

// Every alias below is a thin name onto the generated OpenAPI schema, as above:
// nothing is hand-written, so a backend reshape is a compile error at the use
// site rather than a silent mismatch.

// ── Conversation gauge — owner: Developer 3A (L3-02, L3-03) ──
/** How the sales conversation is going. One thing only — not the journey, not
 * qualification, not the background check. Any value may follow any other. */
export type ExporterConversation = Schemas['ExporterConversation'];
export type Conversation = Schemas['ConversationResponse'];
/** One move the server says this user may make, and what it needs. Never a
 * hand-copied table on the client (architecture §7.5). */
export type ConversationMove = Schemas['ConversationMoveResponse'];
export type SetConversationRequest = Schemas['SetConversationRequest'];
/**
 * One row of the shared CRM history log (Developer 1's route).
 *
 * `details` is `dict | None` on the server, which openapi-typescript generates as
 * `Record<string, never>` — a type that admits no keys, so every reader had to
 * cast. Retyped here as what it is: an open bag of values, read defensively.
 */
export type HistoryEntry = Omit<Schemas['HistoryEntryResponse'], 'details'> & {
  details?: Record<string, unknown> | null;
};
export type HistoryList = Omit<Schemas['HistoryListResponse'], 'entries'> & {
  entries: HistoryEntry[];
};
/** The log's dimensions, as the history route documents them. */
export type HistoryDimension =
  | 'journey'
  | 'qualification'
  | 'conversation'
  | 'background_check'
  | 'deal'
  | 'marker'
  | 'profile'
  | 'verification'
  | 'screening'
  // The five F1 dimensions (Developer 1, `history-row.md` §2), added once for every lane.
  | 'check_cycle'
  | 'background_check_approval'
  | 'gst_registration'
  | 'trade'
  | 'pipeline';
export interface HistoryListParams {
  dimension?: HistoryDimension;
  limit?: number;
  offset?: number;
}

// ── Follow-ups — owner: Developer 3A (L3-04) ──
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
  /** Only the check-backs due on or before today — the Overdue tab's view. */
  checkBacksDueOnly?: boolean;
  limit?: number;
  offset?: number;
}

// ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
export type Deal = Schemas['DealResponse'];
export type DealListItem = Schemas['DealListItemResponse'];
export type DealList = Schemas['DealListResponse'];
export type OpenDealRequest = Schemas['OpenDealRequest'];
export type TransitionDealStageRequest = Schemas['TransitionDealStageRequest'];
export type SetDealBuyerRequest = Schemas['SetDealBuyerRequest'];
export type DealBuyer = Schemas['DealBuyerResponse'];
/** One move this user may make from a deal's current stage — served by the API so
 * no screen keeps its own copy of the stage graph (§7.5). */
export type DealStageMove = Schemas['DealStageMoveResponse'];
/** OPEN -> GATHERING_PAPERWORK -> HANDED_OVER, or WITHDRAWN. Both ends terminal. */
export type DealStage = Schemas['DealStage'];

/** Which document categories a deal must have before handover (plan P2-5a). */
export type DealRequiredDocument = Schemas['DealRequiredDocumentResponse'];
export type DealRequiredDocuments = Schemas['DealRequiredDocumentsResponse'];
export type SetDealRequiredDocumentRequest = Schemas['SetDealRequiredDocumentRequest'];
/** The ten fixed document categories — architecture §3.4. */
export type DocumentCategoryValue = Schemas['DocumentCategory'];

export interface DealListParams {
  /** Repeatable: several stages narrow the list to those stages. */
  stages?: DealStage[];
  limit?: number;
  offset?: number;
}

export type CrmDocument = Schemas['DocumentResponse'];
export type DocumentList = Schemas['DocumentListResponse'];
export type DocumentCategoryOption = Schemas['DocumentCategoryResponse'];
export type DocumentCategoryList = Schemas['DocumentCategoryListResponse'];
export type DocumentDownloadLink = Schemas['DownloadLinkResponse'];
/** The ten fixed categories — architecture §3.4. Which owner each belongs to is a
 * server rule; ask `GET /documents/categories` rather than hard-coding it. */
export type DocumentCategory = Schemas['DocumentCategory'];
export type DocumentSource = Schemas['DocumentSource'];
/** PENDING_SCAN -> AVAILABLE | QUARANTINED | SCAN_FAILED. Only AVAILABLE is
 * downloadable, and `CrmDocument.is_downloadable` already says so — branch on that
 * rather than re-deriving it per screen. */
export type DocumentScanStatus = Schemas['DocumentScanStatus'];
export type DocumentOwnerKind = Schemas['DocumentOwnerKind'];

export interface DocumentListParams {
  /** Repeatable: several categories narrow the list. */
  categories?: DocumentCategory[];
  limit?: number;
  offset?: number;
}

export interface UploadDocumentInput {
  file: File;
  category: DocumentCategory;
  documentType: string;
  source?: DocumentSource;
}

// ══ Dev4 seam — anchor blocks for Developers 4A and 4B (4B-0) ══
// Two parallel pull requests add aliases here, so each owner adds only inside its
// own block. Dev4B may also edit the existing `Verification*` / `Screening*` /
// `BankActivity*` aliases above; Dev4A may not.

// ── Background check — owner: Developer 4A ──
// (4A appends here; 4B does not.)
//
// Aliases of the generated schema, never hand-written shapes: if the API changes
// and the panel does not, `tsc` says so here rather than the screen quietly
// rendering `undefined`.
export type BackgroundCheck =
  components['schemas']['BackgroundCheckResponse'];
export type BackgroundCheckState =
  components['schemas']['BackgroundCheckState'];
export type BackgroundCheckRisk =
  components['schemas']['BackgroundCheckRisk'];
export type BackgroundCheckMove =
  components['schemas']['BackgroundCheckMoveResponse'];
export type BackgroundCheckDecision =
  components['schemas']['BackgroundCheckDecisionResponse'];
export type BackgroundCheckDecisionList =
  components['schemas']['BackgroundCheckDecisionListResponse'];
export type BackgroundCheckEvidenceItem =
  components['schemas']['EvidenceItemResponse'];
export type RecordBackgroundCheckDecisionRequest =
  components['schemas']['RecordBackgroundCheckDecisionRequest'];

// ── Verification and screening — owner: Developer 4B ──
// (4B appends here; 4A does not.)
//
// Aliases of the generated schema only, like everything above.
export type VerificationResultStatus =
  components['schemas']['VerificationResultStatus'];
export type VerificationRiskLevel = components['schemas']['VerificationRiskLevel'];
export type VerificationReview = components['schemas']['VerificationReviewResponse'];
export type VerificationCapabilities =
  components['schemas']['VerificationCapabilities'];
/** An evidence reference a request sends (`document` or `url`). Named
 * `VerificationEvidenceRef*` in the schema so it cannot collide with qualification's
 * `EvidenceRefModel` / `EvidenceRefOut`. */
export type VerificationEvidenceRef =
  components['schemas']['VerificationEvidenceRefModel'];
/** An evidence reference as stored on a result. */
export type VerificationEvidenceRefStored =
  components['schemas']['VerificationEvidenceRefOut'];
/** A BUYER check's subject as it was when recorded, masked by the server per role. */
export type BuyerSnapshot = components['schemas']['BuyerSnapshotResponse'];
/** One checklist item as the server's catalogue defines it: key, label, section. */
export type ScreeningCatalogueItem =
  components['schemas']['ScreeningCatalogueItemResponse'];
export type ScreeningCapabilities = components['schemas']['ScreeningCapabilities'];
export type ScreeningItemHistory = components['schemas']['ScreeningItemHistoryResponse'];

// ── Compliance engine — owner: Developer 1 (allocation §3) ──
// (Developer 1 appends here.) Aliases of the generated schema only.
/** The company's compliance facts now: Clear, its expiry, sanctions and AML (F1). */
export type CompanyComplianceFacts =
  components['schemas']['CompanyComplianceFactsResponse'];
/** PASSED | FAILED | MISSING | PENDING. */
export type ComplianceCheckState = CompanyComplianceFacts['sanctions'];
/** One KYC/KYB round of the background check (P2-3). */
export type CheckCycle = components['schemas']['CheckCycleResponse'];
export type CheckCycleList = components['schemas']['CheckCycleListResponse'];
/** A Re-KYC / Re-KYB this viewer may start now, as served. */
export type BackgroundCheckCycleAction =
  components['schemas']['BackgroundCheckCycleActionResponse'];
export type StartCheckCycleRequest = components['schemas']['StartCheckCycleRequest'];
export type StartCheckCycleResponse = components['schemas']['StartCheckCycleResponse'];
/** What one decision rested on, resolved (P2-1a). */
export type DecisionEvidence = components['schemas']['DecisionEvidenceResponse'];
export type DecisionEvidenceItem = components['schemas']['DecisionEvidenceItemResponse'];
export type DecisionEvidenceVerification =
  components['schemas']['DecisionEvidenceVerification'];
export type DecisionEvidenceScreeningItem =
  components['schemas']['DecisionEvidenceScreeningItem'];
export type DecisionEvidenceDocument = components['schemas']['DecisionEvidenceDocument'];
/** A proposed CLEAR, FLAGGED or ON_HOLD and how it ended — maker-checker (P3-1). */
export type BackgroundCheckProposal =
  components['schemas']['BackgroundCheckProposalResponse'];
export type BackgroundCheckProposalList =
  components['schemas']['BackgroundCheckProposalListResponse'];
/** APPROVE | REJECT | WITHDRAW — what this viewer may do with a proposal, as served. */
export type BackgroundCheckProposalAction = NonNullable<
  BackgroundCheckProposal['allowed_actions']
>[number];
export type ApproveBackgroundCheckProposalResponse =
  components['schemas']['ApproveBackgroundCheckProposalResponse'];
/** One verification type CLEAR requires (rule B, P3-2) and its state. */
export type RequiredCheck = components['schemas']['RequiredCheckResponse'];
/** A company whose Clear has expired or soon will (P3-3c). */
export type ReKycDueCompany = components['schemas']['ReKycDueCompanyResponse'];
export type ReKycDueList = components['schemas']['ReKycDueListResponse'];
