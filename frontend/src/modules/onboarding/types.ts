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
export type ContactStatus = Schemas['ContactStatus'];
export type CompanyAddress = Schemas['CompanyAddressResponse'];
export type CompanyAddressList = Schemas['CompanyAddressListResponse'];
export type CompanyAddressType = Schemas['CompanyAddressType'];
export type AddCompanyAddressRequest = Schemas['AddCompanyAddressRequest'];
export type UpdateCompanyAddressRequest = Schemas['UpdateCompanyAddressRequest'];
export type BankAccount = Schemas['BankAccountResponse'];
export type BankAccountList = Schemas['BankAccountListResponse'];
export type BankAccountStatus = Schemas['BankAccountStatus'];
export type BankAccountType = Schemas['BankAccountType'];
export type BankVerificationMethod = Schemas['BankVerificationMethod'];
export type PendingBankAccount = Schemas['PendingBankAccountResponse'];
export type PendingBankAccountList = Schemas['PendingBankAccountListResponse'];
export type ProposeBankAccountRequest = Schemas['ProposeBankAccountRequest'];
export type VerifyBankAccountRequest = Schemas['VerifyBankAccountRequest'];
export type RevealedBankAccount = Schemas['RevealedBankAccountResponse'];
export type PaymentTerm = Schemas['PaymentTermResponse'];
export type PaymentTermList = Schemas['PaymentTermListResponse'];
export type AddPaymentTermRequest = Schemas['AddPaymentTermRequest'];
export type RevisePaymentTermRequest = Schemas['RevisePaymentTermRequest'];
export type SetDealTermsRequest = Schemas['SetDealTermsRequest'];
export type AssignCollectionsOwnerRequest = Schemas['AssignCollectionsOwnerRequest'];
export type BulkCollectorReassignRequest = Schemas['BulkCollectorReassignRequest'];
export type CompanyGroup = Schemas['CompanyGroupResponse'];
export type GroupMember = Schemas['GroupMemberResponse'];
export type SetParentCompanyRequest = Schemas['SetParentCompanyRequest'];
export type GroupSuggestionList = Schemas['GroupSuggestionListResponse'];
export type SanctionsList = Schemas['SanctionsListResponse'];
export type SanctionsLists = Schemas['SanctionsListsResponse'];
export type AddSanctionsListRequest = Schemas['AddSanctionsListRequest'];
export type ReviseSanctionsListRequest = Schemas['ReviseSanctionsListRequest'];
export type CompanySanctions = Schemas['CompanySanctionsResponse'];
export type SanctionsSubject = Schemas['SubjectCoverageResponse'];
export type SanctionsRun = Schemas['RunResponse'];
export type SanctionsRunList = Schemas['RunListOfCompanyResponse'];
export type SanctionsHit = Schemas['HitResponse'];
export type SanctionsDisposition = Schemas['DispositionResponse']['disposition'];
export type RecordSanctionsRunRequest = Schemas['RecordRunRequest'];
export type SanctionsHitRequest = Schemas['HitRequest'];
export type PendingTrueMatchList = Schemas['PendingTrueMatchListResponse'];
export type RescreenDueList = Schemas['RescreenDueListResponse'];
export type SetContactStatusRequest = Schemas['SetContactStatusRequest'];
export type AddExporterContactRequest = Schemas['AddExporterContactRequest'];
export type UpdateExporterContactRequest = Schemas['UpdateExporterContactRequest'];
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
 * a version is never edited. */
export type Criterion = Schemas['CriterionResponse'];
export type CriterionKind = Schemas['CriterionKind'];
export type ThresholdComparison = Schemas['ThresholdComparison'];
export type CreateCriterionRequest = Schemas['CreateCriterionRequest'];
export type CriterionDefinitionRequest = Schemas['CriterionDefinitionRequest'];

// ── Company intake ──
export type IntakeResult = Schemas['IntakeResponse'];
export type ImportReport = Schemas['ImportReportResponse'];
export type ImportRow = Schemas['ImportRowResponse'];
export type ImportPreview = Schemas['ImportPreviewResponse'];

// ── Who is working on it ──
export type AssignRelationshipManagerRequest = Schemas['AssignRelationshipManagerRequest'];
export type RelationshipManagerAction = NonNullable<
  ExporterProfileDetail['relationship_manager_actions']
>[number];
export type BulkReassignRequest = Schemas['BulkReassignRequest'];
export type BulkReassignResult = Schemas['BulkReassignResponse'];
export type StaffMember = Schemas['StaffMemberResponse'];
export type StaffList = Schemas['StaffListResponse'];
/** The roles a staff picker can ask for: RMs, or reviewers (COMPLIANCE and ADMIN). */
export type PickableRole = 'OPERATIONS' | 'COMPLIANCE' | 'ADMIN';
/** The list's owner filter: My companies, Unassigned, an RM whose account is
 * deactivated, or one RM by id. A filter only — ownership never narrows what a
 * reader may see. */
export type RelationshipManagerFilter = 'me' | 'none' | 'inactive' | (string & {});

export interface ExporterSearchParams {
  name?: string;
  gstin?: string;
  pan?: string;
  iec?: string;
  source?: ExporterSource;
  journey?: ExporterJourney;
  qualification?: QualificationState;
  marker?: ExporterMarker;
  relationship_manager?: RelationshipManagerFilter;
  /** Only companies with no active primary contact. */
  missing_primary_contact?: boolean;
  /** `me` (My collections), `none`, or a user id. */
  collections_owner?: string;
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

// ── Conversation gauge ──
/** How the sales conversation is going. One thing only — not the journey, not
 * qualification, not the background check. Any value may follow any other. */
export type ExporterConversation = Schemas['ExporterConversation'];
export type Conversation = Schemas['ConversationResponse'];
/** One move the server says this user may make, and what it needs. Never a
 * hand-copied table on the client (architecture §7.5). */
export type ConversationMove = Schemas['ConversationMoveResponse'];
export type SetConversationRequest = Schemas['SetConversationRequest'];
/**
 * One row of the shared CRM history log.
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
  // The five newer dimensions (`history-row.md` §2), added together.
  | 'check_cycle'
  | 'background_check_approval'
  | 'gst_registration'
  | 'trade'
  | 'pipeline'
  // Who is working on the company (7 October 2026).
  | 'relationship_manager'
  | 'background_check_assignment'
  // A contact's status or verification.
  | 'contact'
  // A company address added, changed, made a default or deactivated.
  | 'address'
  // A bank account proposed, approved, rejected, verified, made primary or deactivated.
  | 'bank_account'
  // Who chases the company's payments.
  | 'collections_owner'
  // A company linked under a parent, or taken out of its group.
  | 'group'
  // A sanctions screening recorded, or a decision on one of its possible matches.
  | 'sanctions';
export interface HistoryListParams {
  dimension?: HistoryDimension;
  limit?: number;
  offset?: number;
}

// ── Follow-ups ──
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

// ── Deals, buyers, storage and documents ──
export type Deal = Schemas['DealResponse'];
export type DealListItem = Schemas['DealListItemResponse'];
export type DealList = Schemas['DealListResponse'];
export type OpenDealRequest = Schemas['OpenDealRequest'];
export type TransitionDealStageRequest = Schemas['TransitionDealStageRequest'];
export type SetDealBuyerRequest = Schemas['SetDealBuyerRequest'];
/** A buyer company to create and name in one step. */
export type CreateBuyerCompanyRequest = Schemas['CreateBuyerCompanyRequest'];
/** Which of the seller's GST registrations a deal is invoiced from; `null` clears it. */
export type SetDealInvoicingBranchRequest = Schemas['SetDealInvoicingBranchRequest'];
export type DealBuyer = Schemas['DealBuyerResponse'];
/** One move this user may make from a deal's current stage — served by the API so
 * no screen keeps its own copy of the stage graph (§7.5). */
export type DealStageMove = Schemas['DealStageMoveResponse'];
/** OPEN -> GATHERING_PAPERWORK -> HANDED_OVER, or WITHDRAWN. Both ends terminal. */
export type DealStage = Schemas['DealStage'];

/** Which document categories a deal must have before handover. */
export type DealRequiredDocument = Schemas['DealRequiredDocumentResponse'];
export type DealRequiredDocuments = Schemas['DealRequiredDocumentsResponse'];
export type SetDealRequiredDocumentRequest = Schemas['SetDealRequiredDocumentRequest'];
/** The ten fixed document categories — architecture §3.4. */
export type DocumentCategoryValue = Schemas['DocumentCategory'];

export interface DealListParams {
  /** Repeatable: several stages narrow the list to those stages. */
  stages?: DealStage[];
  /**
   * Which side of its deals to list. `seller` (the default) is the deals
   * this company sells on; `buyer` the ones it buys on. Two lists, never one: the
   * same company can be seller on one deal and buyer on another, and `buyer_name`
   * means "the other party", so a mixed list would read differently row by row.
   */
  as?: DealSide;
  limit?: number;
  offset?: number;
}

/** `seller` | `buyer` — which side of a deal a company is on. */
export type DealSide = Schemas['DealSide'];

/** Every deal, across companies — `GET /deals`. */
export type AllDeals = Schemas['AllDealsResponse'];
/** One row of it: both parties, and the corridor between them. */
export type DealSummary = Schemas['DealSummaryResponse'];
/** A corridor some deal is on (`IN-US`, or `null` for not known yet) and how many are. */
export type DealCorridor = Schemas['DealCorridorResponse'];

export interface AllDealsParams {
  /** `IN-US` form, or `UNKNOWN_CORRIDOR` (`constants.ts`). Several widen the list to any of them. */
  corridors?: string[];
  stages?: DealStage[];
  /** Part of the reference, the seller's name or the buyer's name. */
  q?: string;
  /** That company as seller or as buyer company. */
  companyId?: string;
  /** ISO timestamps: from inclusive, before exclusive. */
  openedFrom?: string;
  openedBefore?: string;
  limit?: number;
  offset?: number;
}

/** "Do we already have this company?" — `POST /companies/match`. */
export type CompanyMatchRequest = Schemas['CompanyMatchRequest'];
export type CompanyMatch = Schemas['CompanyMatchResponse'];
export type CompanyMatchCandidate = Schemas['CompanyMatchCandidate'];
/** One company with no `identity_type` and what it lacks (the identity completion list). */
export type IdentityCompletionItem = Schemas['IdentityCompletionItem'];
export type IdentityCompletionList = Schemas['IdentityCompletionListResponse'];
/** MATCHED | POSSIBLE_DUPLICATE | CONFLICT | NEW. */
export type CompanyMatchKind = CompanyMatch['kind'];

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

// ══ Compliance blocks ══
// Each area adds aliases only inside its own block.

// ── Background check ──
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

// ── Verification and screening ──
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

// ── Compliance engine ──
// Aliases of the generated schema only.
/** The company's compliance facts now: Clear, its expiry, sanctions and AML. */
export type CompanyComplianceFacts =
  components['schemas']['CompanyComplianceFactsResponse'];
/** PASSED | FAILED | MISSING | PENDING. */
export type ComplianceCheckState = CompanyComplianceFacts['sanctions'];
/** One KYC/KYB round of the background check. */
export type CheckCycle = components['schemas']['CheckCycleResponse'];
export type CheckCycleList = components['schemas']['CheckCycleListResponse'];
/** A Re-KYC / Re-KYB this viewer may start now, as served. */
export type BackgroundCheckCycleAction =
  components['schemas']['BackgroundCheckCycleActionResponse'];
export type StartCheckCycleRequest = components['schemas']['StartCheckCycleRequest'];
export type StartCheckCycleResponse = components['schemas']['StartCheckCycleResponse'];
/** What one decision rested on, resolved. */
export type DecisionEvidence = components['schemas']['DecisionEvidenceResponse'];
export type DecisionEvidenceItem = components['schemas']['DecisionEvidenceItemResponse'];
export type DecisionEvidenceVerification =
  components['schemas']['DecisionEvidenceVerification'];
export type DecisionEvidenceScreeningItem =
  components['schemas']['DecisionEvidenceScreeningItem'];
export type DecisionEvidenceDocument = components['schemas']['DecisionEvidenceDocument'];
/** A proposed CLEAR, FLAGGED or ON_HOLD and how it ended — maker-checker. */
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
/** One verification type CLEAR requires and its state. */
export type RequiredCheck = components['schemas']['RequiredCheckResponse'];
/** A company whose Clear has expired or soon will. */
export type ReKycDueCompany = components['schemas']['ReKycDueCompanyResponse'];
export type ReKycDueList = components['schemas']['ReKycDueListResponse'];

/** Bring a buyer-only company into the sales pipeline. */
export type BringIntoPipelineRequest = Schemas['BringIntoPipelineRequest'];

// ── GST registrations: a company's branches ──────────────────────────────────

/** One branch: a state, an address, a portal status, and possibly a flag. */
export type GstRegistration = Schemas['GstRegistrationResponse'];
export type GstRegistrationList = Schemas['GstRegistrationListResponse'];
export type AddGstRegistrationRequest = Schemas['AddGstRegistrationRequest'];
export type FlagGstRegistrationRequest = Schemas['FlagGstRegistrationRequest'];
/** UNVERIFIED | ACTIVE | CANCELLED | SUSPENDED — what the GST portal says. */
export type GstRegistrationStatus = GstRegistration['status'];

// ── Trade history: what two companies have invoiced and settled (3.18–3.22) ──

/** The other party on a relationship: an id, a name, a country, a pipeline status.
 * **No identifiers, for any role** — a counterparty's PAN or GSTIN is on its own
 * company page, where its masking applies to it. */
export type TradeCounterparty = Schemas['TradeCounterparty'];
/** One ordered (seller, buyer) pair. A selling to B is not B selling to A. */
export type TradeRelationship = Schemas['TradeRelationshipResponse'];
export type TradeRelationshipList = Schemas['TradeRelationshipListResponse'];
export type TradeRelationshipDetail = Schemas['TradeRelationshipDetailResponse'];
/** One invoice, carrying the outcome we currently believe. `amount` is a **string**:
 * money is `Numeric` server-side and a JSON number would round it. */
export type TradeInvoice = Schemas['TradeInvoiceResponse'];
/** An invoice and its whole outcome chain, oldest first. */
export type TradeInvoiceDetail = Schemas['TradeInvoiceDetailResponse'];
/** One thing we learned about an invoice. Never edited; superseded. */
export type TradeOutcome = Schemas['TradeOutcomeResponse'];
/** PAID | UNPAID | PARTIAL | DISPUTED | UNKNOWN. `UNKNOWN` is an answer, not a gap. */
export type TradePaymentStatus = Schemas['TradePaymentStatus'];
/** PROVEN | CLAIMED — whether anything backs the outcome up. */
export type TradeProofStatus = Schemas['TradeProofStatus'];
export type RecordTradeInvoiceRequest = Schemas['RecordTradeInvoiceRequest'];
export type RecordTradeOutcomeRequest = Schemas['RecordTradeOutcomeRequest'];
export type RecordDealPaymentOutcomeRequest = Schemas['RecordDealPaymentOutcomeRequest'];
export type DealPaymentOutcome = Schemas['DealPaymentOutcomeResponse'];

// ── Who holds the review, and the worklists ──
export type ReviewAction = NonNullable<BackgroundCheck['review_actions']>[number];
export type ComplianceWorkItem = components['schemas']['ComplianceWorkItemResponse'];
export type ComplianceWorklist = components['schemas']['ComplianceWorklistResponse'];
export type ComplianceWorkView = 'awaiting' | 'mine' | 'in_review' | 'overdue' | 'needs_attention';
export type WorklistCounts = components['schemas']['WorklistCountsResponse'];
export type RecentDecision = components['schemas']['RecentDecisionResponse'];
export type RecentDecisionList = components['schemas']['RecentDecisionListResponse'];
