/**
 * One company's paperwork — **owner: Developer 3B** (L3-09, L3-11b).
 *
 * The company page's Documents tab. (It was a route of its own,
 * `/exporters/:customerId/documents`, while the company page was one long
 * scroll; the old address now redirects here.) Only the categories that belong
 * to a company are offered — the server serves them for `owner=COMPANY`.
 *
 * Deal paperwork lives on the deal (`DealDetailPage`), because architecture §3.4
 * files a document against a company **or** a deal and the two lists answer
 * different questions.
 */

import { Upload } from 'lucide-react';
import { useState } from 'react';

import { Button, FormPanel, Panel } from '@/components';

import { DocumentList, DocumentUpload } from '../../components';
import { useCompanyDocuments, useUploadCompanyDocument } from '../../hooks';

export function DocumentsPanel({
  customerId,
  isStaff,
}: {
  customerId: string;
  isStaff: boolean;
}) {
  const documents = useCompanyDocuments(customerId);
  const upload = useUploadCompanyDocument(customerId);
  const [uploading, setUploading] = useState(false);

  return (
    <Panel
      title="Company documents"
      description="Paperwork that belongs to the relationship rather than to one deal."
      actions={
        isStaff &&
        !uploading && (
          <Button size="sm" variant="primary" onClick={() => setUploading(true)}>
            <Upload size={14} />
            Upload a document
          </Button>
        )
      }
    >
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
    </Panel>
  );
}
