/**
 * One company's paperwork — **owner: Developer 3B** (L3-11b).
 *
 * Its own route rather than a section on the company page, for two reasons: the
 * company page's panels are owned one each by Developers 2, 3 and 4 and the shell is
 * closed, and company-wide paperwork is a list someone comes to deliberately rather
 * than something to scroll past on the way to the conversation.
 *
 * Deal paperwork lives on the deal (`DealDetailPage`), because architecture §3.4
 * files a document against a company **or** a deal and the two lists answer
 * different questions.
 */

import { ArrowLeft, FolderOpen } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { FormPanel } from '@/components';
import { useCurrentUser } from '@/platform/auth';

import { DocumentList, DocumentUpload } from '../components';
import {
  useCompanyDocuments,
  useExporterProfileDetail,
  useUploadCompanyDocument,
} from '../hooks';

export function DocumentsPage() {
  const { customerId } = useParams<{ customerId: string }>();
  const user = useCurrentUser();
  const isStaff = ['OPERATIONS', 'COMPLIANCE', 'ADMIN'].includes(user.role);

  const profile = useExporterProfileDetail(customerId);
  const documents = useCompanyDocuments(customerId);
  const upload = useUploadCompanyDocument(customerId ?? '');
  const [uploading, setUploading] = useState(false);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <Link
          to={`/exporters/${customerId}`}
          className="inline-flex items-center gap-1.5 text-sm text-ink-muted hover:text-ink"
        >
          <ArrowLeft size={14} /> Back to the company
        </Link>
      </div>

      <section className="rounded-xl border border-border bg-surface p-5">
        <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="flex items-center gap-2 text-lg font-semibold text-ink">
              <FolderOpen size={17} className="text-ink-faint" />
              Company documents
            </h1>
            <p className="mt-0.5 text-sm text-ink-muted">
              {profile.data?.name ?? 'This company'} — paperwork that belongs to the
              relationship rather than to one deal.
            </p>
          </div>
          {isStaff && !uploading && (
            <button
              type="button"
              onClick={() => setUploading(true)}
              className="rounded-lg bg-ink px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
            >
              Upload a document
            </button>
          )}
        </div>

        {uploading && (
          <FormPanel title="Upload a document" onClose={() => setUploading(false)}>
            <DocumentUpload
              owner="COMPANY"
              isUploading={upload.isPending}
              onUpload={(input) => upload.mutateAsync(input)}
              onDone={() => setUploading(false)}
            />
          </FormPanel>
        )}

        <DocumentList
          documents={documents.data?.documents ?? []}
          isLoading={documents.isLoading}
          emptyMessage="No company documents yet."
        />
      </section>
    </div>
  );
}
