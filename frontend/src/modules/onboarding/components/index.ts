export { JourneyChip, MarkerBadge, QualificationChip } from './CompanyChips';
export { MarkerControl } from './MarkerControl';
export { DuplicatePanMessage } from './DuplicatePanMessage';
export { duplicatePanHolder } from './duplicate-pan';
export { VerificationSection } from './VerificationSection';
// Developer 4B: checks on a deal's buyer, mounted on the deal page.
export { BuyerChecks } from './BuyerChecks';
// Developer 3A: the conversation gauge's move control, and the READY_NOW prompt
// (seam S2), which opens a deal through Developer 3B's `OpenDealForm`.
export { ConversationGaugeControl } from './ConversationGaugeControl';
export { OpenDealPrompt } from './OpenDealPrompt';
// Developer 3B: deals and documents. `DocumentUpload` and `DocumentList` are
// shared by the company page's Documents tab and the deal page, because a
// document row and an upload form read the same wherever they hang;
// `ScanStatusBadge` says which "scanner" reached a verdict.
export { DealStageChip } from './DealStageChip';
export { OpenDealForm } from './OpenDealForm';
// Developer 2 (allocation F2): a company's deals in one role. Mounted on the
// company page by Developer 3 (task 3.9); filled by task 2.7.
export { CompanyDealsList } from './CompanyDealsList';
export { GstRegistrationsSection } from './GstRegistrationsSection';
export type { GstRegistrationsSectionProps } from './GstRegistrationsSection';
export { NotInPipelineNotice } from './NotInPipelineNotice';
export { IdentityGapNotice } from './IdentityGapNotice';
export type { NotInPipelineNoticeProps } from './NotInPipelineNotice';
export type { CompanyDealsListProps } from './CompanyDealsList';
export { DocumentList } from './DocumentList';
export { DocumentUpload } from './DocumentUpload';
export { ScanStatusBadge } from './ScanStatusBadge';
// Developer 1: the shared history log, and who acted, by name.
export { CompanyHistory, DealHistory } from './HistoryTimeline';
export { actorLabel } from './actor-label';

// ── Background check — owner: Developer 4A ──
export { BackgroundCheckGauge } from './BackgroundCheckGauge';
export { RiskChip } from './RiskChip';
export { BackgroundCheckMoveDialog } from './BackgroundCheckMoveDialog';
export { DecisionHistory } from './DecisionHistory';

// ── Company record, GST branches, trade history — owner: Developer 3 ──
// Mounted by other lanes: Developer 2 on the deal page (the buyer picker in 2.4, the
// trade history in 2.11). Both began as F3 stubs with final props, which is why
// filling them (3.10, 3.22) changed no mounting.
export { CompanyPicker } from './CompanyPicker';
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
// The one write on the deal page (P5-6): how a handed-over deal was paid. Staff only,
// and only on a handed-over deal with a buyer company.
export { RecordDealOutcomeForm } from './RecordDealOutcomeForm';
export { RecordPastTradeForm } from './RecordPastTradeForm';
export type { RecordDealOutcomeFormProps } from './RecordDealOutcomeForm';
export type { TradeOutcomeChipProps } from './TradeOutcomeChip';
// Which of the seller's GST branches a deal is invoiced from (task 2.8): the handover
// guard asks for it whenever the seller has an active registration (task 2.9).
export { InvoicingBranchPicker } from './InvoicingBranchPicker';
export type { InvoicingBranchPickerProps } from './InvoicingBranchPicker';

// ── Compliance engine — owner: Developer 1 ──
// Mounted by other lanes: Developer 2 on the deal page (seller and buyer company).
export { CompanyComplianceSummary } from './CompanyComplianceSummary';
