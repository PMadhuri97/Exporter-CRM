/**
 * The conversation as something you move along (frontend-plan §6.2) — **owner:
 * Developer 3A** (L3-03, L3-04a), replacing `ConversationGaugeControl`.
 *
 *   Not contacted ── Reaching out ── Spoke to them ── Interested ── Ready now
 *                                                         └── Not now  ‖ check back 12 Nov
 *
 * Every node is drawn; **only the nodes the server listed in `allowed_moves` are
 * buttons** — the rest are inert, and with no moves the track is a picture of where
 * the conversation stands. Choosing a node opens a small popover asking exactly what
 * the server says that move needs: a check-back date where `check_back_required`, a
 * reason where `reason_required` (optional otherwise). The lamp moves when the server
 * answers, not before — one ring travels from the old node to the new (§5.4, 240 ms,
 * instant under reduced motion); a refusal is shown in the server's words.
 *
 * Still no copy of the conversation rules: the order of the nodes is the drawing,
 * not a transition table.
 */

import { useLayoutEffect, useRef, useState, type CSSProperties } from 'react';
import { toast } from 'sonner';

import { Button, Input, Popover, PopoverContent, PopoverTrigger, Textarea } from '@/components';
import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';
import { formatDate } from '@/lib/format';

import { useSetExporterConversation } from '../../hooks';
import type { ConversationMove, ExporterConversation } from '../../types';

import { Lamp } from './Lamp';
import { CONVERSATION_LAMP, CONVERSATION_TRACK } from './lamps';

/** Today in the browser's timezone, as the `YYYY-MM-DD` a date input takes. */
function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

function MoveForm({
  customerId,
  move,
  close,
}: {
  customerId: string;
  move: ConversationMove;
  close: () => void;
}) {
  const mutation = useSetExporterConversation(customerId);
  const [reason, setReason] = useState('');
  const [checkBackOn, setCheckBackOn] = useState('');
  const label = CONVERSATION_LAMP[move.to].label;

  return (
    <form
      className="space-y-3"
      onSubmit={(event) => {
        event.preventDefault();
        mutation.mutate(
          {
            conversation: move.to,
            reason: reason.trim() || null,
            // Sent only where the server asks for it: anywhere else it is refused.
            check_back_on: move.check_back_required ? checkBackOn || null : null,
          },
          {
            onSuccess: () => {
              toast.success(`Conversation: ${label}`);
              close();
            },
            onError: (error) => toast.error(error.message),
          },
        );
      }}
    >
      <p className="text-body font-medium text-ink">Move to {label}</p>
      {move.check_back_required && (
        <label className="block text-caption font-medium text-ink-2" htmlFor="conversation-check-back">
          Check back on
          <Input
            id="conversation-check-back"
            type="date"
            className="mt-1"
            value={checkBackOn}
            onChange={(event) => setCheckBackOn(event.target.value)}
            // Only stops the picker offering a past day; the server still decides.
            min={localToday()}
            required
          />
        </label>
      )}
      <label className="block text-caption font-medium text-ink-2" htmlFor="conversation-reason">
        Reason{move.reason_required ? '' : ' (optional)'}
        <Textarea
          id="conversation-reason"
          className="mt-1 min-h-[4rem]"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          required={move.reason_required}
        />
      </label>
      <div className="flex justify-end gap-2">
        <Button variant="quiet" size="sm" onClick={close}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" size="sm" loading={mutation.isPending}>
          Confirm
        </Button>
      </div>
    </form>
  );
}

/**
 * Where the ring marking the current node sits, measured from the drawing. `null`
 * until it can be measured (no layout yet, or a test without one): the current node
 * then draws its own ring, so the track never shows without one.
 *
 * The ring travels when the value moves. When the track itself is resized (the window,
 * the rail pinned) it snaps instead: travelling then left it trailing its node.
 */
function useTravellingRing(value: ExporterConversation) {
  const track = useRef<HTMLDivElement>(null);
  const [ring, setRing] = useState<CSSProperties | null>(null);
  useLayoutEffect(() => {
    const container = track.current;
    if (!container) return;
    let size = '';
    const place = (travel: boolean) => {
      const node = container.querySelector<HTMLElement>('[aria-current="step"]');
      const box = node?.getBoundingClientRect();
      const outer = container.getBoundingClientRect();
      size = `${outer.width}x${outer.height}`;
      if (!node || !box || box.width === 0) {
        setRing(null);
        return;
      }
      setRing({
        left: box.left - outer.left,
        top: box.top - outer.top,
        width: box.width,
        height: box.height,
        ...(travel ? {} : { transition: 'none' }),
      });
    };
    place(true);
    // The observer also reports the size it starts with; only a change re-places.
    const observer =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            const outer = container.getBoundingClientRect();
            if (`${outer.width}x${outer.height}` !== size) place(false);
          });
    observer?.observe(container);
    return () => observer?.disconnect();
  }, [value]);
  return { track, ring };
}

function Node({
  value,
  current,
  move,
  customerId,
  detail,
  ringed,
}: {
  value: ExporterConversation;
  current: boolean;
  move: ConversationMove | undefined;
  customerId: string;
  detail?: string;
  /** The travelling ring is drawn behind this node, so it draws none of its own. */
  ringed: boolean;
}) {
  const [open, setOpen] = useState(false);
  const look = CONVERSATION_LAMP[value];
  const face = (
    <>
      <Lamp shape={look.shape} meaning={look.meaning} size={14} />
      <span className="whitespace-nowrap">{look.label}</span>
      {detail && <span className="whitespace-nowrap text-ink-3">· {detail}</span>}
    </>
  );
  const base = 'relative inline-flex items-center gap-2 rounded-md px-2.5 py-1.5 text-secondary';

  if (!move) {
    return (
      <span
        className={cn(
          base,
          current
            ? cn('font-semibold text-ink', !ringed && 'bg-surface ring-1 ring-ink')
            : 'text-ink-3',
        )}
        aria-current={current ? 'step' : undefined}
      >
        {face}
      </span>
    );
  }
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        className={cn(
          base,
          'border border-dashed border-line-strong font-medium text-ink transition-colors duration-quick hover:border-ink hover:bg-sunken',
        )}
      >
        {face}
      </PopoverTrigger>
      <PopoverContent className="w-80">
        <MoveForm customerId={customerId} move={move} close={() => setOpen(false)} />
      </PopoverContent>
    </Popover>
  );
}

export function GaugeTrack({
  customerId,
  value,
  checkBackOn,
  moves,
}: {
  customerId: string;
  value: ExporterConversation;
  checkBackOn?: string | null;
  /** Exactly what the server served. Empty: nothing on the track is a button. */
  moves: ConversationMove[];
}) {
  const moveTo = (to: ExporterConversation) => moves.find((move) => move.to === to);
  const notNowDetail = value === 'NOT_NOW' && checkBackOn ? `check back ${formatDate(checkBackOn)}` : undefined;
  const { track, ring } = useTravellingRing(value);

  return (
    <div ref={track} className="relative space-y-2" data-testid="gauge-track">
      {ring && (
        <span
          aria-hidden
          className="pointer-events-none absolute rounded-md bg-surface ring-1 ring-ink transition-[left,top,width,height] duration-travel ease-enter"
          style={ring}
        />
      )}
      <ol aria-label="Conversation" className="flex flex-wrap items-center gap-y-2">
        {CONVERSATION_TRACK.map((step, index) => (
          <li key={step} className="flex items-center">
            {index > 0 && <span aria-hidden className="mx-1 h-px w-4 bg-line-strong sm:w-6" />}
            <Node
              value={step}
              current={value === step}
              move={moveTo(step)}
              customerId={customerId}
              ringed={ring !== null}
            />
          </li>
        ))}
      </ol>
      {/* "Not now" branches off the track: a pause, not a stage. */}
      <div className="flex items-center gap-2 pl-1">
        <Icon.caretRight size={12} className="text-ink-4" aria-hidden />
        <Node
          value="NOT_NOW"
          current={value === 'NOT_NOW'}
          move={moveTo('NOT_NOW')}
          customerId={customerId}
          detail={notNowDetail}
          ringed={ring !== null}
        />
      </div>
    </div>
  );
}
