/**
 * One company's paperwork.
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

import { Panel } from '@/components';

import { DocumentsByCategory } from '../../components';
import { useCompanyDocuments, useUploadCompanyDocument } from '../../hooks';

/** The Documents tab: the company's documents by category (frontend-plan §8.5), upload for staff. */
export function DocumentsPanel({
  customerId,
  isStaff,
}: {
  customerId: string;
  isStaff: boolean;
}) {
  const documents = useCompanyDocuments(customerId);
  const upload = useUploadCompanyDocument(customerId);

  return (
    <Panel
      title="Company documents"
      description="Paperwork that belongs to the relationship rather than to one deal."
    >
      <DocumentsByCategory
        documents={documents.data?.documents ?? []}
        isLoading={documents.isLoading}
        emptyMessage="No company documents yet."
        upload={
          isStaff
            ? {
                owner: 'COMPANY',
                isUploading: upload.isPending,
                onUpload: (input) => upload.mutateAsync(input),
              }
            : undefined
        }
      />
    </Panel>
  );
}
