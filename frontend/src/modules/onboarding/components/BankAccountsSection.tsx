/**
 * A company's bank accounts.
 *
 * * **Numbers masked.** Every account shows `••••5678`. *Reveal* — only for a reader
 *   the server says may (`capabilities.can_reveal`) — asks the server for the full
 *   number, which audits it, and shows it on that row until the page is left.
 * * **Status on every account**: pending approval, pending verification, verified,
 *   rejected or inactive. Rejected and inactive versions sit behind *Show history*.
 * * **Propose** a new account, or a **change** to a verified one: the old account stays
 *   in force until the change is verified.
 * * **Approve** appears only where the server says this reader may approve that
 *   account (`can_approve`), which follows the approval mode — the proposer never sees
 *   it where a second person is needed. **Reject, verify, make primary, deactivate**
 *   are for a reader who may approve (`capabilities.can_approve`).
 * * **Verify** with a cancelled cheque or bank letter on the company's record, or a
 *   passed bank-account verification of the company (penny drop).
 */

import { useState } from 'react';
import { toast } from 'sonner';

import {
  Badge,
  Button,
  EmptySection,
  Field,
  FormPanel,
  Input,
  Panel,
  RequiredNote,
  Select,
  Skeleton,
  Textarea,
} from '@/components';
import { Icon } from '@/design/icons';
import { formatDate } from '@/lib/format';

import {
  useBankAccountAction,
  useBankAccounts,
  useCompanyDocuments,
  useProposeBankAccount,
  useRevealBankAccount,
  useVerificationResults,
} from '../hooks';
import type {
  BankAccount,
  BankAccountType,
  BankVerificationMethod,
  ProposeBankAccountRequest,
} from '../types';

import {
  BANK_METHOD_LABEL,
  BANK_STATUS_LABEL,
  BANK_STATUS_TONE,
  BANK_TYPE_LABEL,
} from './bank-account-labels';

const TYPES = Object.keys(BANK_TYPE_LABEL) as BankAccountType[];
const PAST = new Set(['REJECTED', 'INACTIVE']);

interface ProposalForm {
  account_holder_name: string;
  bank_name: string;
  branch: string;
  account_number: string;
  iban: string;
  ifsc: string;
  swift_bic: string;
  currency: string;
  account_type: BankAccountType;
  ad_code: string;
  reason: string;
}

function blankFor(replacing?: BankAccount): ProposalForm {
  return {
    account_holder_name: replacing?.account_holder_name ?? '',
    bank_name: replacing?.bank_name ?? '',
    branch: replacing?.branch ?? '',
    account_number: '',
    iban: '',
    ifsc: replacing?.ifsc ?? '',
    swift_bic: replacing?.swift_bic ?? '',
    currency: replacing?.currency ?? 'INR',
    account_type: replacing?.account_type ?? 'CURRENT',
    ad_code: replacing?.ad_code ?? '',
    reason: '',
  };
}

function ProposeForm({
  customerId,
  replacing,
  onDone,
}: {
  customerId: string;
  /** The verified account a change replaces. */
  replacing?: BankAccount;
  onDone: () => void;
}) {
  const propose = useProposeBankAccount(customerId);
  const [form, setForm] = useState<ProposalForm>(blankFor(replacing));
  const set = (key: keyof ProposalForm, value: string) => setForm((prev) => ({ ...prev, [key]: value }));
  const ready =
    form.account_holder_name.trim() &&
    form.bank_name.trim() &&
    (form.account_number.trim() || form.iban.trim()) &&
    form.currency.trim().length === 3;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!ready) return;
    const text = (value: string) => value.trim() || null;
    const body: ProposeBankAccountRequest = {
      account_holder_name: form.account_holder_name.trim(),
      bank_name: form.bank_name.trim(),
      branch: text(form.branch),
      account_number: text(form.account_number),
      iban: text(form.iban),
      ifsc: text(form.ifsc),
      swift_bic: text(form.swift_bic),
      currency: form.currency.trim().toUpperCase(),
      account_type: form.account_type,
      ad_code: text(form.ad_code),
      reason: text(form.reason),
      replaces_id: replacing?.id ?? null,
    };
    try {
      await propose.mutateAsync(body);
      toast.success(replacing ? 'Change proposed for approval' : 'Bank account proposed for approval');
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not propose the account');
    }
  }

  const input = (key: keyof ProposalForm, label: string, required = false, placeholder?: string) => (
    <Field label={label} htmlFor={`bank-${key}`} required={required}>
      <Input
        id={`bank-${key}`}
        value={form[key]}
        placeholder={placeholder}
        onChange={(event) => set(key, event.target.value)}
      />
    </Field>
  );

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      {replacing && (
        <p className="rounded-md bg-sunken px-3 py-2 text-secondary text-ink-2">
          Replaces the account ending {replacing.account_number_masked ?? replacing.iban_masked}. It
          stays in use until this change is approved and verified.
        </p>
      )}
      {input('account_holder_name', 'Account holder name', true)}
      <div className="grid gap-3 sm:grid-cols-2">
        {input('bank_name', 'Bank', true)}
        {input('branch', 'Branch')}
        {input('account_number', 'Account number', false, 'Or give the IBAN')}
        {input('iban', 'IBAN', false, 'Foreign accounts')}
        {input('ifsc', 'IFSC', false, 'e.g. HDFC0000060')}
        {input('swift_bic', 'SWIFT / BIC', false, 'e.g. HDFCINBB')}
        {input('currency', 'Currency', true, 'e.g. INR, USD')}
        <Field label="Account type" htmlFor="bank-account_type" required>
          <Select
            id="bank-account_type"
            value={form.account_type}
            onChange={(event) => set('account_type', event.target.value)}
          >
            {TYPES.map((type) => (
              <option key={type} value={type}>
                {BANK_TYPE_LABEL[type]}
              </option>
            ))}
          </Select>
        </Field>
        {input('ad_code', 'AD code', false, 'Authorised Dealer code')}
      </div>
      <Field label="Why" htmlFor="bank-reason">
        <Textarea id="bank-reason" rows={2} value={form.reason} onChange={(e) => set('reason', e.target.value)} />
      </Field>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!ready} loading={propose.isPending}>
          Propose for approval
        </Button>
      </div>
    </form>
  );
}

function VerifyForm({
  customerId,
  account,
  onDone,
}: {
  customerId: string;
  account: BankAccount;
  onDone: () => void;
}) {
  const action = useBankAccountAction(customerId);
  const documents = useCompanyDocuments(customerId);
  const results = useVerificationResults('EXPORTER', customerId);
  const [method, setMethod] = useState<BankVerificationMethod>('CANCELLED_CHEQUE');
  const [evidence, setEvidence] = useState('');
  const penny = method === 'PENNY_DROP';
  const available = (documents.data?.documents ?? []).filter((doc) => doc.scan_status === 'AVAILABLE');
  const passed = (results.data?.results ?? []).filter(
    (result) => result.verification_type === 'BANK_ACCOUNT' && result.status === 'PASSED',
  );

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!evidence) return;
    try {
      await action.mutateAsync({
        action: 'verify',
        accountId: account.id,
        body: penny
          ? { method, verification_result_id: evidence }
          : { method, evidence_document_id: evidence },
      });
      toast.success('Bank account verified');
      onDone();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not verify the account');
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <RequiredNote />
      <Field label="How was it verified" htmlFor="bank-method" required>
        <Select
          id="bank-method"
          value={method}
          onChange={(event) => {
            setMethod(event.target.value as BankVerificationMethod);
            setEvidence('');
          }}
        >
          {(Object.keys(BANK_METHOD_LABEL) as BankVerificationMethod[]).map((value) => (
            <option key={value} value={value}>
              {BANK_METHOD_LABEL[value]}
            </option>
          ))}
        </Select>
      </Field>
      <Field label={penny ? 'Passed verification' : 'Document'} htmlFor="bank-evidence" required>
        <Select id="bank-evidence" value={evidence} onChange={(event) => setEvidence(event.target.value)}>
          <option value="">{penny ? 'Choose a verification' : 'Choose a document'}</option>
          {penny
            ? passed.map((result) => (
                <option key={result.id} value={result.id}>
                  {result.provider} · {formatDate(result.performed_at)}
                </option>
              ))
            : available.map((doc) => (
                <option key={doc.id} value={doc.id}>
                  {doc.file_name}
                </option>
              ))}
        </Select>
      </Field>
      {!penny && available.length === 0 && (
        <p className="text-caption text-ink-3">
          Upload the cancelled cheque or bank letter on the Documents tab first.
        </p>
      )}
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!evidence} loading={action.isPending}>
          Verify
        </Button>
      </div>
    </form>
  );
}

function ReasonForm({
  label,
  submitLabel,
  busy,
  onSubmit,
  onDone,
}: {
  label: string;
  submitLabel: string;
  busy: boolean;
  onSubmit: (reason: string) => Promise<void>;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  return (
    <form
      className="space-y-4"
      onSubmit={async (event) => {
        event.preventDefault();
        if (!reason.trim()) return;
        await onSubmit(reason.trim());
      }}
    >
      <RequiredNote />
      <Field label={label} htmlFor="bank-action-reason" required>
        <Textarea id="bank-action-reason" rows={3} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <div className="flex justify-end gap-2 border-t border-line pt-4">
        <Button onClick={onDone}>Cancel</Button>
        <Button type="submit" variant="primary" disabled={!reason.trim()} loading={busy}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}

type Sheet =
  | { kind: 'propose'; replacing?: BankAccount }
  | { kind: 'verify'; account: BankAccount }
  | { kind: 'reject' | 'deactivate'; account: BankAccount };

export interface BankAccountsSectionProps {
  customerId: string;
}

export function BankAccountsSection({ customerId }: BankAccountsSectionProps) {
  const query = useBankAccounts(customerId);
  const action = useBankAccountAction(customerId);
  const reveal = useRevealBankAccount();
  const [sheet, setSheet] = useState<Sheet | null>(null);
  const [showPast, setShowPast] = useState(false);
  const [revealed, setRevealed] = useState<Record<string, string>>({});

  const accounts = query.data?.accounts ?? [];
  const capabilities = query.data?.capabilities;
  const past = accounts.filter((account) => PAST.has(account.status));
  const shown = showPast ? accounts : accounts.filter((account) => !PAST.has(account.status));
  const changing = new Set(
    accounts
      .filter((a) => a.replaces_id && (a.status === 'PENDING_APPROVAL' || a.status === 'PENDING_VERIFICATION'))
      .map((a) => a.replaces_id),
  );

  const run = async (work: Promise<unknown>, done: string) => {
    try {
      await work;
      toast.success(done);
      setSheet(null);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'That did not work');
    }
  };

  async function show(account: BankAccount) {
    try {
      const numbers = await reveal.mutateAsync(account.id);
      setRevealed((prev) => ({ ...prev, [account.id]: numbers.account_number ?? numbers.iban ?? '' }));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not reveal the number');
    }
  }

  return (
    <Panel
      title="Bank accounts"
      actions={
        capabilities?.can_propose && (
          <Button size="sm" onClick={() => setSheet({ kind: 'propose' })}>
            <Icon.add size={14} /> Propose account
          </Button>
        )
      }
    >
      {sheet && (
        <FormPanel
          title={
            sheet.kind === 'propose'
              ? sheet.replacing
                ? 'Propose a change'
                : 'Propose a bank account'
              : sheet.kind === 'verify'
                ? 'Verify the account'
                : sheet.kind === 'reject'
                  ? 'Reject the account'
                  : 'Deactivate the account'
          }
          onClose={() => setSheet(null)}
        >
          {sheet.kind === 'propose' ? (
            <ProposeForm customerId={customerId} replacing={sheet.replacing} onDone={() => setSheet(null)} />
          ) : sheet.kind === 'verify' ? (
            <VerifyForm customerId={customerId} account={sheet.account} onDone={() => setSheet(null)} />
          ) : (
            <ReasonForm
              label={sheet.kind === 'reject' ? 'Why is it rejected' : 'Why stop using it'}
              submitLabel={sheet.kind === 'reject' ? 'Reject' : 'Deactivate'}
              busy={action.isPending}
              onDone={() => setSheet(null)}
              onSubmit={(reason) =>
                run(
                  action.mutateAsync({ action: sheet.kind, accountId: sheet.account.id, reason }),
                  sheet.kind === 'reject' ? 'Bank account rejected' : 'Bank account deactivated',
                )
              }
            />
          )}
        </FormPanel>
      )}

      {query.isLoading ? (
        <Skeleton className="h-20 rounded-lg" />
      ) : accounts.length === 0 ? (
        <EmptySection>No bank accounts recorded.</EmptySection>
      ) : (
        <>
          <ul className="divide-y divide-line overflow-hidden rounded-lg border border-line">
            {shown.map((account) => (
              <li
                key={account.id}
                data-testid="bank-account-row"
                className={`px-4 py-3 ${PAST.has(account.status) ? 'bg-paper' : ''}`}
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex flex-wrap items-center gap-2">
                      <span className="font-medium text-ink">
                        {account.bank_name} · {account.currency} {BANK_TYPE_LABEL[account.account_type]}
                      </span>
                      <Badge tone={BANK_STATUS_TONE[account.status]}>{BANK_STATUS_LABEL[account.status]}</Badge>
                      {account.is_primary && <Badge variant="outline">Primary</Badge>}
                      {account.replaces_id && !PAST.has(account.status) && account.status !== 'VERIFIED' && (
                        <Badge variant="outline">Change</Badge>
                      )}
                    </p>
                    <p className="mt-0.5 text-body text-ink-2">
                      {account.account_holder_name} ·{' '}
                      <span className="tabular-nums" data-testid="bank-number">
                        {revealed[account.id] ?? account.account_number_masked ?? account.iban_masked}
                      </span>
                      {account.ifsc ? ` · IFSC ${account.ifsc}` : ''}
                      {account.swift_bic ? ` · SWIFT ${account.swift_bic}` : ''}
                    </p>
                    <p className="mt-0.5 text-caption text-ink-3">
                      {account.status === 'VERIFIED' && account.verification_method
                        ? `Verified by ${BANK_METHOD_LABEL[account.verification_method]}${account.verified_at ? `, ${formatDate(account.verified_at)}` : ''}`
                        : `Proposed${account.proposed_by_name ? ` by ${account.proposed_by_name}` : ''}, ${formatDate(account.created_at)}`}
                      {account.rejection_reason ? ` · Rejected: ${account.rejection_reason}` : ''}
                      {account.deactivation_reason ? ` · ${account.deactivation_reason}` : ''}
                    </p>
                  </div>
                  <div className="flex shrink-0 flex-wrap items-center gap-2">
                    {capabilities?.can_reveal && !revealed[account.id] && (
                      <Button size="sm" variant="subtle" onClick={() => void show(account)}>
                        <Icon.reveal size={14} /> Reveal
                      </Button>
                    )}
                    {account.can_approve && (
                      <Button
                        size="sm"
                        variant="primary"
                        disabled={action.isPending}
                        onClick={() =>
                          void run(
                            action.mutateAsync({ action: 'approve', accountId: account.id }),
                            'Approved — now verify it',
                          )
                        }
                      >
                        Approve
                      </Button>
                    )}
                    {capabilities?.can_approve && account.status === 'PENDING_VERIFICATION' && (
                      <Button size="sm" variant="primary" onClick={() => setSheet({ kind: 'verify', account })}>
                        Verify
                      </Button>
                    )}
                    {capabilities?.can_approve &&
                      (account.status === 'PENDING_APPROVAL' || account.status === 'PENDING_VERIFICATION') && (
                        <Button size="sm" variant="subtle" onClick={() => setSheet({ kind: 'reject', account })}>
                          Reject
                        </Button>
                      )}
                    {account.status === 'VERIFIED' && capabilities?.can_propose && !changing.has(account.id) && (
                      <Button
                        size="sm"
                        variant="subtle"
                        onClick={() => setSheet({ kind: 'propose', replacing: account })}
                      >
                        Propose change
                      </Button>
                    )}
                    {account.status === 'VERIFIED' && capabilities?.can_approve && !account.is_primary && (
                      <Button
                        size="sm"
                        variant="subtle"
                        disabled={action.isPending}
                        onClick={() =>
                          void run(
                            action.mutateAsync({ action: 'primary', accountId: account.id }),
                            'Primary account changed',
                          )
                        }
                      >
                        Make primary
                      </Button>
                    )}
                    {account.status === 'VERIFIED' && capabilities?.can_approve && (
                      <Button size="sm" variant="subtle" onClick={() => setSheet({ kind: 'deactivate', account })}>
                        Deactivate
                      </Button>
                    )}
                  </div>
                </div>
              </li>
            ))}
          </ul>
          {past.length > 0 && (
            <button
              type="button"
              onClick={() => setShowPast((value) => !value)}
              className="mt-2 text-secondary text-accent hover:underline"
            >
              {showPast ? 'Hide history' : `Show history (${past.length})`}
            </button>
          )}
        </>
      )}
    </Panel>
  );
}
