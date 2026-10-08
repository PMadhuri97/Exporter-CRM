/**
 * The company's relationship manager: one RM user, set through its own route.
 *
 * What this user may do is served by the server (`relationship_manager_actions`), so
 * nothing here knows the rule: an RM sees **Assign to me** on a company with no RM; ADMIN
 * and holders of `exporters:assign_rm` see **Assign**, **Change** and **Clear**, the last
 * two with a reason; everyone else — compliance included — reads the name. An RM whose
 * account has been deactivated is flagged, so a manager can move the company on.
 *
 * Every request sends the RM the screen showed (`seen_user_id`): if someone changed it
 * meanwhile the server refuses and the message says so, rather than overwriting them.
 * Being the RM grants nothing — identifiers stay masked for the RM like for any RM user.
 */

import { useState } from 'react';
import { toast } from 'sonner';

import { Button, Field, FormError, Select, Tag, Textarea } from '@/components';
import { Icon } from '@/design/icons';
import { ApiError } from '@/lib/api/errors';
import { useCurrentUser } from '@/platform/auth';

import { useAssignRelationshipManager, useStaff } from '../hooks';
import type { ExporterProfileDetail, RelationshipManagerAction } from '../types';

type Mode = Exclude<RelationshipManagerAction, 'CLAIM'>;

const TITLES: Record<Mode, string> = {
  ASSIGN: 'Assign a relationship manager',
  CHANGE: 'Change the relationship manager',
  CLEAR: 'Clear the relationship manager',
};

export function RelationshipManagerName({
  name,
  inactive,
}: {
  name: string | null | undefined;
  inactive?: boolean;
}) {
  if (!name) return <span className="text-ink-3">Unassigned</span>;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      <span>{name}</span>
      {inactive && (
        <Tag tone="attention" icon={<Icon.warning size={11} aria-hidden />}>
          Deactivated
        </Tag>
      )}
    </span>
  );
}

export function RelationshipManagerField({ profile }: { profile: ExporterProfileDetail }) {
  const user = useCurrentUser();
  const actions = profile.relationship_manager_actions ?? [];
  const current = profile.relationship_manager_user_id ?? null;
  const assign = useAssignRelationshipManager(profile.customer_id);
  const [mode, setMode] = useState<Mode | null>(null);
  const [target, setTarget] = useState('');
  const [reason, setReason] = useState('');
  const picking = mode === 'ASSIGN' || mode === 'CHANGE';
  const staff = useStaff(['OPERATIONS'], picking);

  const reset = () => {
    setMode(null);
    setTarget('');
    setReason('');
    assign.reset();
  };

  const send = (userId: string | null, why: string | null, done: string) =>
    assign.mutate(
      { user_id: userId, seen_user_id: current, reason: why },
      {
        onSuccess: () => {
          toast.success(done);
          reset();
        },
      },
    );

  const needsReason = mode === 'CHANGE' || mode === 'CLEAR';
  const canSubmit =
    !assign.isPending &&
    (!picking || target !== '') &&
    (!needsReason || reason.trim().length > 0);

  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <RelationshipManagerName
          name={profile.relationship_manager_name}
          inactive={profile.relationship_manager_inactive}
        />
        {mode === null &&
          actions.map((action) =>
            action === 'CLAIM' ? (
              <Button
                key={action}
                size="sm"
                variant="secondary"
                loading={assign.isPending}
                onClick={() => send(user.id, null, 'You are now the relationship manager')}
              >
                Assign to me
              </Button>
            ) : (
              <Button key={action} size="sm" variant="subtle" onClick={() => setMode(action)}>
                {action === 'ASSIGN' ? 'Assign' : action === 'CHANGE' ? 'Change' : 'Clear'}
              </Button>
            ),
          )}
      </div>
      {mode === null && assign.isError && (
        <p role="alert" className="mt-1 text-caption text-negative">
          {assign.error instanceof ApiError ? assign.error.message : 'Could not change the RM.'}
        </p>
      )}
      {profile.relationship_manager && !profile.relationship_manager_name && (
        <p className="mt-1 text-caption text-ink-3">
          Recorded before RMs were users: “{profile.relationship_manager}”
        </p>
      )}

      {mode !== null && (
        <div
          role="dialog"
          aria-label={TITLES[mode]}
          className="mt-2 max-w-sm space-y-3 rounded-lg border border-line bg-surface p-3"
        >
          <h4 className="text-body font-semibold text-ink">{TITLES[mode]}</h4>
          {picking && (
            <Field label="Relationship manager" htmlFor="rm-picker" required>
              <Select
                id="rm-picker"
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                disabled={staff.isLoading}
              >
                <option value="">{staff.isLoading ? 'Loading…' : 'Choose an RM'}</option>
                {(staff.data?.staff ?? [])
                  .filter((member) => member.id !== current)
                  .map((member) => (
                    <option key={member.id} value={member.id}>
                      {member.name} ({member.companies} compan{member.companies === 1 ? 'y' : 'ies'})
                    </option>
                  ))}
              </Select>
            </Field>
          )}
          {needsReason && (
            <Field label="Reason" htmlFor="rm-reason" required>
              <Textarea
                id="rm-reason"
                rows={2}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              />
            </Field>
          )}
          <FormError>
            {assign.isError &&
              (assign.error instanceof ApiError ? assign.error.message : 'Could not change the RM.')}
          </FormError>
          <div className="flex gap-2">
            <Button
              size="sm"
              variant={mode === 'CLEAR' ? 'destructive' : 'primary'}
              disabled={!canSubmit}
              loading={assign.isPending}
              onClick={() =>
                mode === 'CLEAR'
                  ? send(null, reason.trim(), 'Relationship manager cleared')
                  : send(
                      target,
                      needsReason ? reason.trim() : null,
                      'Relationship manager updated',
                    )
              }
            >
              {mode === 'CLEAR' ? 'Clear' : 'Save'}
            </Button>
            <Button size="sm" variant="subtle" onClick={reset}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
