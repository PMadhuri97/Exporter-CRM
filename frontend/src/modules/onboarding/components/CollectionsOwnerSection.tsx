/**
 * Who chases a company's payments. Shown to every reader; changed only by a holder of
 * `exporters:assign_collector` (compliance and the sales lead), who may name any active
 * staff member. Changing or clearing an owner asks why; the screen sends the owner it
 * showed, so a change someone else made meanwhile is refused rather than overwritten.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, Panel, Select, Textarea } from '@/components';
import { useHasPermission } from '@/platform/access';

import { useAssignCollectionsOwner, useStaff } from '../hooks';

export interface CollectionsOwnerSectionProps {
  customerId: string;
  ownerId: string | null | undefined;
  ownerName: string | null | undefined;
}

export function CollectionsOwnerSection({ customerId, ownerId, ownerName }: CollectionsOwnerSectionProps) {
  const canAssign = useHasPermission('exporters:assign_collector');
  const staff = useStaff(['OPERATIONS', 'COMPLIANCE'], canAssign);
  const assign = useAssignCollectionsOwner(customerId);
  const [choice, setChoice] = useState(ownerId ?? '');
  const [reason, setReason] = useState('');
  const changed = choice !== (ownerId ?? '');
  const needsReason = changed && Boolean(ownerId);

  function save() {
    assign.mutate(
      { user_id: choice || null, seen_user_id: ownerId ?? null, reason: reason.trim() || null },
      {
        onSuccess: () => {
          toast.success(choice ? 'Collections owner set' : 'Collections owner cleared');
          setReason('');
        },
        onError: (error) =>
          toast.error(error instanceof Error ? error.message : 'Could not change the collections owner'),
      },
    );
  }

  return (
    <Panel title="Collections">
      {!canAssign ? (
        <p className="text-body text-ink">
          <span className="text-ink-3">Collections owner: </span>
          {ownerName ?? (ownerId ? 'Unknown user' : 'Not assigned')}
        </p>
      ) : (
        <div className="space-y-3">
          <Field label="Collections owner" htmlFor="collections-owner">
            <Select id="collections-owner" value={choice} onChange={(event) => setChoice(event.target.value)}>
              <option value="">Not assigned</option>
              {ownerId && !(staff.data?.staff ?? []).some((member) => member.id === ownerId) && (
                <option value={ownerId}>{ownerName ?? 'Current owner'}</option>
              )}
              {(staff.data?.staff ?? []).map((member) => (
                <option key={member.id} value={member.id}>
                  {member.name}
                </option>
              ))}
            </Select>
          </Field>
          {needsReason && (
            <Field label="Why the change" htmlFor="collections-reason" required>
              <Textarea id="collections-reason" rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
            </Field>
          )}
          {changed && (
            <div className="flex justify-end gap-2">
              <Button size="sm" onClick={() => setChoice(ownerId ?? '')}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                disabled={needsReason && !reason.trim()}
                loading={assign.isPending}
                onClick={save}
              >
                Save
              </Button>
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}
