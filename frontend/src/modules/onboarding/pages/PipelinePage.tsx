import { useMemo, useState, type DragEvent } from 'react';
import { GripVertical, Search, ShieldAlert } from 'lucide-react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import { useCurrentUser } from '@/platform/auth';
import { MaskedValue } from '@/platform/mask';

import { LifecycleMoveControl, StageChip } from '../components';
import {
  PERMITTED_LIFECYCLE_TRANSITIONS,
  STAGE_GROUP_CHIP_CLASSES,
  STAGE_GROUP_LABEL,
  STATUS_LABEL,
  STATUS_TO_STAGE_GROUP,
  canMoveLifecycleFrom,
  type StageGroup,
} from '../constants';
import { useExporterProfiles, useTransitionExporterLifecycle } from '../hooks';
import type {
  ExporterLifecycleStatus,
  ExporterProfileListItem,
} from '../types';

/** Pipeline columns intentionally exclude exit states. Suspended/offboarded
 * exporters live in the separate inactive view, per EXP-F10 decision #1. */
export const PIPELINE_STAGE_GROUPS = [
  'NEW',
  'CONTACTED',
  'ONBOARDING',
  'APPROVED',
  'ACTIVE',
] as const satisfies readonly StageGroup[];

type PipelineStageGroup = (typeof PIPELINE_STAGE_GROUPS)[number];

type ViewMode = 'PIPELINE' | 'INACTIVE';

/**
 * Resolve a grouped kanban column to the one exact backend status that a
 * drag is allowed to enact. Intra-column transitions are deliberately not
 * mapped to a drag: when two exact lifecycle states share one visual column,
 * a same-column drop would be ambiguous and easy to trigger accidentally.
 * Those transitions remain available through the shared EXP-F6 Move-to menu.
 */
export function legalDropTargetForGroup(
  currentStatus: ExporterLifecycleStatus,
  targetGroup: PipelineStageGroup,
): ExporterLifecycleStatus | null {
  const currentGroup = STATUS_TO_STAGE_GROUP[currentStatus];
  if (currentGroup === targetGroup) return null;

  const matches = PERMITTED_LIFECYCLE_TRANSITIONS[currentStatus].filter(
    (status) => STATUS_TO_STAGE_GROUP[status] === targetGroup,
  );

  // Destructured rather than `matches[0]`: under `noUncheckedIndexedAccess`
  // an index read stays `| undefined` no matter what `matches.length` was
  // just checked to be, so this states the "exactly one" condition in a
  // form the compiler can actually follow.
  const [match, ...rest] = matches;
  return match !== undefined && rest.length === 0 ? match : null;
}

export function legalDropGroups(
  currentStatus: ExporterLifecycleStatus,
): PipelineStageGroup[] {
  return PIPELINE_STAGE_GROUPS.filter(
    (group) => legalDropTargetForGroup(currentStatus, group) !== null,
  );
}

function PipelineSkeleton() {
  return (
    <div className="grid min-w-[1100px] grid-cols-5 gap-4">
      {PIPELINE_STAGE_GROUPS.map((group) => (
        <div key={group} className="rounded-xl border border-border bg-surface-subtle p-3">
          <div className="mb-3 h-5 w-24 animate-pulse rounded bg-surface-sunken" />
          <div className="space-y-3">
            {Array.from({ length: 2 }).map((_, index) => (
              <div key={index} className="h-36 animate-pulse rounded-lg border border-border bg-surface" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

interface PipelineCardProps {
  profile: ExporterProfileListItem;
  onDragStart: (profile: ExporterProfileListItem) => void;
  onDragEnd: () => void;
}

function PipelineCard({
  profile,
  onDragStart,
  onDragEnd,
}: PipelineCardProps) {
  const { role } = useCurrentUser();
  const canMove = canMoveLifecycleFrom(profile.lifecycle_status, role);
  const crossColumnMoves = legalDropGroups(profile.lifecycle_status);
  const draggable = canMove && crossColumnMoves.length > 0;

  return (
    <article
      draggable={draggable}
      onDragStart={(event) => {
        if (!draggable) {
          event.preventDefault();
          return;
        }
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', profile.customer_id);
        onDragStart(profile);
      }}
      onDragEnd={onDragEnd}
      className={`rounded-lg border border-border bg-surface p-3 shadow-card transition-shadow ${
        draggable ? 'cursor-grab active:cursor-grabbing hover:shadow-md' : ''
      }`}
      data-testid={`pipeline-card-${profile.customer_id}`}
    >
      <div className="flex items-start gap-2">
        <GripVertical
          size={16}
          className={`mt-0.5 shrink-0 ${draggable ? 'text-ink-faint' : 'text-border-strong'}`}
          aria-hidden="true"
        />
        <div className="min-w-0 flex-1">
          <Link
            to={`/exporters/${profile.customer_id}`}
            className="block truncate text-sm font-semibold text-ink hover:text-brand-600"
          >
            {profile.legal_name ?? 'Unnamed lead'}
          </Link>
          <div className="mt-1">
            <StageChip status={profile.lifecycle_status} showDetail />
          </div>
        </div>
      </div>

      <dl className="mt-3 space-y-1.5 text-xs">
        <div className="flex items-center justify-between gap-3">
          <dt className="text-ink-faint">PAN</dt>
          <dd className="min-w-0 text-right text-ink-muted">
            <MaskedValue value={profile.pan} />
          </dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-ink-faint">GSTIN</dt>
          <dd className="min-w-0 text-right text-ink-muted">
            <MaskedValue value={profile.gstin} />
          </dd>
        </div>
        <div className="flex items-center justify-between gap-3">
          <dt className="text-ink-faint">Owner</dt>
          <dd className="truncate text-right font-medium text-ink-muted">
            {profile.relationship_manager ?? 'Unassigned'}
          </dd>
        </div>
      </dl>

      <div className="mt-3 border-t border-border pt-3">
        <LifecycleMoveControl
          customerId={profile.customer_id}
          currentStatus={profile.lifecycle_status}
        />
      </div>

      {canMove &&
        !draggable &&
        PERMITTED_LIFECYCLE_TRANSITIONS[profile.lifecycle_status].length > 0 && (
          <p className="mt-2 text-[11px] leading-4 text-ink-faint">
            Next lifecycle move stays in this column. Use Move to…
          </p>
        )}
    </article>
  );
}

interface PipelineColumnProps {
  group: PipelineStageGroup;
  profiles: ExporterProfileListItem[];
  draggingProfile: ExporterProfileListItem | null;
  isMoving: boolean;
  onDrop: (group: PipelineStageGroup) => void;
  onDragStart: (profile: ExporterProfileListItem) => void;
  onDragEnd: () => void;
}

function PipelineColumn({
  group,
  profiles,
  draggingProfile,
  isMoving,
  onDrop,
  onDragStart,
  onDragEnd,
}: PipelineColumnProps) {
  const targetStatus = draggingProfile
    ? legalDropTargetForGroup(draggingProfile.lifecycle_status, group)
    : null;
  const dragActive = draggingProfile !== null;
  const isLegalTarget = dragActive && targetStatus !== null;
  const isDisabledTarget = dragActive && !isLegalTarget;

  function handleDragOver(event: DragEvent<HTMLDivElement>) {
    if (!isLegalTarget || isMoving) return;
    event.preventDefault();
    event.dataTransfer.dropEffect = 'move';
  }

  return (
    <section
      onDragOver={handleDragOver}
      onDrop={(event) => {
        event.preventDefault();
        if (isLegalTarget && !isMoving) onDrop(group);
      }}
      aria-disabled={isDisabledTarget || undefined}
      className={`min-h-[560px] rounded-xl border p-3 transition-all ${
        isLegalTarget
          ? 'border-brand-400 bg-brand-50 ring-2 ring-brand-100'
          : isDisabledTarget
            ? 'border-border bg-surface-sunken opacity-55'
            : 'border-border bg-surface-subtle'
      }`}
      data-testid={`pipeline-column-${group}`}
    >
      <header className="mb-3 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span
            className={`rounded-full px-2 py-0.5 text-xs font-semibold ${STAGE_GROUP_CHIP_CLASSES[group]}`}
          >
            {STAGE_GROUP_LABEL[group]}
          </span>
          <span className="text-xs tabular-nums text-ink-faint">{profiles.length}</span>
        </div>
        {isLegalTarget && targetStatus && (
          <span className="text-[11px] font-medium text-brand-600">
            Drop → {STATUS_LABEL[targetStatus]}
          </span>
        )}
        {isDisabledTarget && (
          <span className="text-[11px] font-medium text-ink-faint">Not allowed</span>
        )}
      </header>

      <div className="space-y-3">
        {profiles.map((profile) => (
          <PipelineCard
            key={profile.customer_id}
            profile={profile}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
          />
        ))}
        {profiles.length === 0 && (
          <div className="rounded-lg border border-dashed border-border-strong px-3 py-8 text-center text-xs text-ink-faint">
            No exporters in this stage
          </div>
        )}
      </div>
    </section>
  );
}

export function PipelinePage() {
  const [viewMode, setViewMode] = useState<ViewMode>('PIPELINE');
  const [searchInput, setSearchInput] = useState('');
  const [legalName, setLegalName] = useState('');
  const [draggingProfile, setDraggingProfile] =
    useState<ExporterProfileListItem | null>(null);
  const [movingCustomerId, setMovingCustomerId] = useState<string | null>(null);

  const { data, isLoading, isError } = useExporterProfiles({
    legalName: legalName || undefined,
    limit: 100,
  });

  const dragMutation = useTransitionExporterLifecycle(
    draggingProfile?.customer_id ?? '__pipeline_drag__',
  );

  const profiles = useMemo(() => data?.profiles ?? [], [data]);
  const activeProfiles = useMemo(
    () => profiles.filter((profile) => STATUS_TO_STAGE_GROUP[profile.lifecycle_status] !== 'INACTIVE'),
    [profiles],
  );
  const inactiveProfiles = useMemo(
    () => profiles.filter((profile) => STATUS_TO_STAGE_GROUP[profile.lifecycle_status] === 'INACTIVE'),
    [profiles],
  );

  const groupedProfiles = useMemo(() => {
    const grouped = Object.fromEntries(
      PIPELINE_STAGE_GROUPS.map((group) => [group, [] as ExporterProfileListItem[]]),
    ) as Record<PipelineStageGroup, ExporterProfileListItem[]>;

    for (const profile of activeProfiles) {
      const group = STATUS_TO_STAGE_GROUP[profile.lifecycle_status];
      if (group !== 'INACTIVE') grouped[group].push(profile);
    }
    return grouped;
  }, [activeProfiles]);

  async function handleDrop(targetGroup: PipelineStageGroup) {
    const profile = draggingProfile;
    if (!profile) return;

    const targetStatus = legalDropTargetForGroup(profile.lifecycle_status, targetGroup);
    if (!targetStatus) return;

    setMovingCustomerId(profile.customer_id);
    try {
      await dragMutation.mutateAsync(targetStatus);
      toast.success(
        `${profile.legal_name ?? 'Exporter'} moved to ${STATUS_LABEL[targetStatus]}`,
      );
    } catch {
      toast.error('Could not move exporter. Refresh and try again.');
    } finally {
      setMovingCustomerId(null);
      setDraggingProfile(null);
    }
  }

  return (
    <div>
      <div className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-lg font-semibold text-ink">Pipeline</h1>
          <p className="text-sm text-ink-muted">
            Move exporters through the lifecycle. Illegal stage jumps are disabled before drop.
          </p>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-surface p-1">
          <button
            type="button"
            onClick={() => setViewMode('PIPELINE')}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              viewMode === 'PIPELINE'
                ? 'bg-ink text-white'
                : 'text-ink-muted hover:bg-surface-subtle'
            }`}
          >
            Pipeline ({activeProfiles.length})
          </button>
          <button
            type="button"
            onClick={() => setViewMode('INACTIVE')}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              viewMode === 'INACTIVE'
                ? 'bg-ink text-white'
                : 'text-ink-muted hover:bg-surface-subtle'
            }`}
          >
            Inactive ({inactiveProfiles.length})
          </button>
        </div>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setLegalName(searchInput.trim());
        }}
        className="mb-5 flex max-w-md items-center gap-2"
      >
        <div className="relative flex-1">
          <Search
            size={16}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint"
          />
          <input
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            placeholder="Search company name…"
            className="w-full rounded-lg border border-border bg-surface py-2 pl-9 pr-3 text-sm text-ink outline-none placeholder:text-ink-faint focus:border-brand-400 focus:ring-2 focus:ring-brand-100"
          />
        </div>
        <button
          type="submit"
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-medium text-ink hover:bg-surface-subtle"
        >
          Search
        </button>
      </form>

      {isError && (
        <div className="mb-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <ShieldAlert size={16} />
          Pipeline data could not be loaded.
        </div>
      )}

      {viewMode === 'PIPELINE' ? (
        <div className="overflow-x-auto pb-4">
          {isLoading ? (
            <PipelineSkeleton />
          ) : (
            <div className="grid min-w-[1100px] grid-cols-5 gap-4">
              {PIPELINE_STAGE_GROUPS.map((group) => (
                <PipelineColumn
                  key={group}
                  group={group}
                  profiles={groupedProfiles[group]}
                  draggingProfile={draggingProfile}
                  isMoving={movingCustomerId !== null}
                  onDrop={(targetGroup) => void handleDrop(targetGroup)}
                  onDragStart={setDraggingProfile}
                  onDragEnd={() => {
                    if (movingCustomerId === null) setDraggingProfile(null);
                  }}
                />
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-xl border border-border bg-surface">
          <div className="border-b border-border px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">Suspended & offboarded</h2>
            <p className="text-xs text-ink-faint">
              Exit states are intentionally kept out of the kanban. Reactivation and other legal moves still use the shared Move to… control.
            </p>
          </div>
          <div className="divide-y divide-border">
            {inactiveProfiles.map((profile) => (
              <div
                key={profile.customer_id}
                className="grid gap-3 px-4 py-3 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-center"
              >
                <div className="min-w-0">
                  <Link
                    to={`/exporters/${profile.customer_id}`}
                    className="truncate text-sm font-semibold text-ink hover:text-brand-600"
                  >
                    {profile.legal_name ?? 'Unnamed lead'}
                  </Link>
                  <p className="mt-0.5 text-xs text-ink-faint">
                    {profile.relationship_manager ?? 'Unassigned'}
                  </p>
                </div>
                <StageChip status={profile.lifecycle_status} showDetail />
                <LifecycleMoveControl
                  customerId={profile.customer_id}
                  currentStatus={profile.lifecycle_status}
                />
              </div>
            ))}
            {!isLoading && inactiveProfiles.length === 0 && (
              <div className="px-4 py-10 text-center text-sm text-ink-faint">
                No suspended or offboarded exporters.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
