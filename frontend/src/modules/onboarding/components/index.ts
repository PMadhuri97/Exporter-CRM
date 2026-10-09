export { MarkerBadge, QualificationChip } from './CompanyChips';
export { MarkerControl } from './MarkerControl';
export { DuplicatePanMessage } from './DuplicatePanMessage';
export { duplicatePanHolder } from './duplicate-pan';
export { VerificationSection } from './VerificationSection';
// Checks on a deal's buyer, mounted on the deal page.
export { BuyerChecks } from './BuyerChecks';
// The conversation gauge's READY_NOW prompt (seam S2), which opens a deal through
// `OpenDealForm`.
export { OpenDealPrompt } from './OpenDealPrompt';
// Deals and documents. `DocumentUpload` and `DocumentsByCategory` are
// shared by the company page's Documents tab and the deal page, because a
// document row and an upload form read the same wherever they hang;
// `ScanStatusBadge` says which "scanner" reached a verdict.
export { DealStageChip } from './DealStageChip';
export { OpenDealForm } from './OpenDealForm';
// The Deals page: its company filter and *New deal*.
export { CompanySearchSelect } from './CompanySearchSelect';
export { NewDealPanel } from './NewDealPanel';
// A company's deals in one role, mounted on the company page.
export { CompanyDealsList } from './CompanyDealsList';
export { AddressesSection, type AddressesSectionProps } from './AddressesSection';
export { BankAccountsSection, type BankAccountsSectionProps } from './BankAccountsSection';
export { CompanyGroupPanel } from './CompanyGroupPanel';
export {
  CollectionsOwnerSection,
  type CollectionsOwnerSectionProps,
} from './CollectionsOwnerSection';
export {
  DefaultPaymentTermSection,
  type DefaultPaymentTermSectionProps,
} from './DefaultPaymentTermSection';
export { ADDRESS_TYPE_LABEL, addressLine } from './address-labels';
export { GstRegistrationsSection } from './GstRegistrationsSection';
export type { GstRegistrationsSectionProps } from './GstRegistrationsSection';
export { NotInPipelineNotice } from './NotInPipelineNotice';
export { IdentityGapNotice } from './IdentityGapNotice';
export type { NotInPipelineNoticeProps } from './NotInPipelineNotice';
export type { CompanyDealsListProps } from './CompanyDealsList';
export { DocumentUpload } from './DocumentUpload';
export { ScanStatusBadge } from './ScanStatusBadge';
// The shared history log, and who acted, by name.
export { CompanyHistory, DealHistory } from './HistoryTimeline';
export { actorLabel } from './actor-label';

// ── Background check ──
export { BackgroundCheckGauge } from './BackgroundCheckGauge';
export { RiskChip } from './RiskChip';
export { BackgroundCheckMoveDialog } from './BackgroundCheckMoveDialog';
export { DecisionHistory } from './DecisionHistory';

// ── Company record, GST branches, trade history ──
// Also mounted on the deal page (the buyer picker and the trade history). Both began
// as stubs with final props, which is why filling them changed no mounting.
export { CompanyPicker } from './CompanyPicker';
export { CountrySelect } from './CountrySelect';
export { CreateBuyerCompanyForm } from './CreateBuyerCompanyForm';
export type { CompanyPickerProps } from './CompanyPicker';
export { TradeHistoryPanel } from './TradeHistoryPanel';
export type { TradeHistoryPanelProps } from './TradeHistoryPanel';
// The company page's half of trade history: who this company trades with, each side
// its own list. `TradeInvoiceList` is what both halves render, and
// `TradeOutcomeChip` keeps "nobody looked" apart from "looked and could not say".
export { CompanyTradePanel } from './CompanyTradePanel';
export type { CompanyTradePanelProps } from './CompanyTradePanel';
export { TradeInvoiceList } from './TradeInvoiceList';
export type { TradeInvoiceListProps } from './TradeInvoiceList';
export { NoOutcomeChip, TradeOutcomeChip } from './TradeOutcomeChip';
// The one write on the deal page: how a handed-over deal was paid. Staff only,
// and only on a handed-over deal with a buyer company.
export { RecordDealOutcomeForm } from './RecordDealOutcomeForm';
export { RecordPastTradeForm } from './RecordPastTradeForm';
export type { RecordDealOutcomeFormProps } from './RecordDealOutcomeForm';
export type { TradeOutcomeChipProps } from './TradeOutcomeChip';
// Which of the seller's GST branches a deal is invoiced from: the handover
// guard asks for it whenever the seller has an active registration.
export { InvoicingBranchPicker } from './InvoicingBranchPicker';
export type { InvoicingBranchPickerProps } from './InvoicingBranchPicker';

// ── Compliance engine ──
// Also mounted on the deal page (seller and buyer company).
export { CompanyComplianceSummary } from './CompanyComplianceSummary';
export * from './record';

// The gauges as worded status badges (frontend-plan §6.4), one per gauge.
export {
  BackgroundCheckBadge,
  ConversationBadge,
  JourneyBadge,
  MarkerStatusBadge,
  OutsidePipelineBadge,
  QualificationBadge,
  RiskBadge,
} from './StatusBadge';

// The company record's right column: related records as cards (frontend-plan §6.6).
export { CompanyRelatedCards } from './CompanyRelatedCards';
export { RelationshipManagerField, RelationshipManagerName } from './RelationshipManagerField';
export { BulkReassignPanel } from './BulkReassignPanel';
export { RelationshipManagerChoice } from './RelationshipManagerChoice';
export { ReviewerLine } from './ReviewerLine';
export { DueChip, WorkItemChips } from './WorkItemChips';
export { STAGE_LABEL, waitedFor } from './work-item-labels';
export { WorklistBadge, type WorklistBadgeKind } from './WorklistBadge';
