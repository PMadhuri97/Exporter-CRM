/**
 * "Who is the relationship manager?" — asked where an action makes a company somebody's:
 * starting its background check and recording it QUALIFIED, on a company with no RM.
 *
 * An RM is offered **Me**, chosen already. ADMIN and holders of `exporters:assign_rm` pick
 * any active RM (themselves first, if they are one). Anyone else — a compliance officer —
 * cannot name one: the dialog says an RM must be set first, and the action waits. The
 * server applies the same rule; this only keeps the screen from offering what it refuses.
 */

import { useEffect } from 'react';

import { Field, Select } from '@/components';
import { useCan, useHasPermission } from '@/platform/access';
import { useCurrentUser } from '@/platform/auth';

import { useStaff } from '../hooks';

export function RelationshipManagerChoice({
  value,
  onChange,
  action,
}: {
  value: string | null;
  onChange: (userId: string | null) => void;
  /** What the RM is needed for, for the sentence: "to start the check". */
  action: string;
}) {
  const user = useCurrentUser();
  const self = useCan('rm.self');
  const lead = useHasPermission('exporters:assign_rm');
  const staff = useStaff(['OPERATIONS'], lead);

  // An RM who may name only themselves is chosen at once: there is nothing to pick.
  useEffect(() => {
    if (self && !lead && value === null) onChange(user.id);
  }, [self, lead, value, onChange, user.id]);

  if (!self && !lead) {
    return (
      <p role="note" className="rounded bg-attention-tint p-2 text-caption text-attention">
        This company has no relationship manager. An RM, an administrator or a sales lead
        must set one {action}.
      </p>
    );
  }

  if (!lead) {
    return (
      <p className="rounded bg-sunken p-2 text-caption text-ink-2">
        This company has no relationship manager: you will become its RM.
      </p>
    );
  }

  const others = (staff.data?.staff ?? []).filter((member) => member.id !== user.id);
  return (
    <Field
      label="Relationship manager"
      htmlFor="rm-choice"
      required
      hint={`This company has no RM yet; one is needed ${action}.`}
    >
      <Select
        id="rm-choice"
        value={value ?? ''}
        onChange={(event) => onChange(event.target.value || null)}
        disabled={staff.isLoading}
      >
        <option value="">{staff.isLoading ? 'Loading…' : 'Choose an RM'}</option>
        {self && <option value={user.id}>Me</option>}
        {others.map((member) => (
          <option key={member.id} value={member.id}>
            {member.name}
          </option>
        ))}
      </Select>
    </Field>
  );
}
