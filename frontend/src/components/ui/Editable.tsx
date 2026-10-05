import { useEffect, useId, useRef, useState, type ReactNode } from 'react';

import { Icon } from '@/design/icons';
import { cn } from '@/lib/cn';

export interface EditableOption {
  value: string;
  label: string;
}

/**
 * A fact you click to change, in place (§6.10) — the replacement for an edit
 * form. Reading, it is text; a role that may edit gets a quiet pencil and the
 * whole value as one button ("Edit Industry"). Editing, Enter or leaving the
 * field saves a changed value, Escape puts the old one back. While the save is
 * in flight the field holds; a refusal stays on screen in the server's words,
 * with the draft kept, so nothing typed is lost.
 *
 * `readOnly` renders the value alone: no pencil, no button, nothing to discover.
 * `trigger="pencil"` makes only the pencil the button, for a value that carries
 * controls of its own (an `Identifier`'s reveal and copy): a button cannot hold buttons.
 */
export function Editable({
  label,
  value,
  onSave,
  kind = 'text',
  options,
  display,
  placeholder = '—',
  inputPlaceholder,
  readOnly = false,
  trigger = 'value',
  className,
}: {
  /** What the fact is — the accessible name of the button and the field. */
  label: string;
  value: string | null;
  /** Called with the new value. A rejection's `message` is shown under the field. */
  onSave: (next: string) => Promise<unknown> | void;
  kind?: 'text' | 'number' | 'select';
  options?: readonly EditableOption[];
  /** How the value reads when not editing (a formatted number, a label for a code). */
  display?: ReactNode;
  placeholder?: string;
  /** Shown in the empty field while editing ("Hidden — type to replace"). */
  inputPlaceholder?: string;
  readOnly?: boolean;
  /** What opens the field: the whole value (default), or only the pencil beside it. */
  trigger?: 'value' | 'pencil';
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? '');
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldRef = useRef<HTMLInputElement & HTMLSelectElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const errorId = useId();

  useEffect(() => {
    if (editing) fieldRef.current?.focus();
  }, [editing]);

  const shown = display ?? (value === null || value === '' ? null : value);

  if (readOnly) {
    return <span className={cn('text-ink', className)}>{shown ?? <span className="text-ink-3">{placeholder}</span>}</span>;
  }

  function close() {
    setEditing(false);
    setError(null);
    // Focus goes back to what opened the field (§11).
    requestAnimationFrame(() => buttonRef.current?.focus());
  }

  async function save(next: string) {
    if (next === (value ?? '')) {
      close();
      return;
    }
    setPending(true);
    setError(null);
    try {
      await onSave(next);
      close();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : 'Could not save this change.');
    } finally {
      setPending(false);
    }
  }

  const open = () => {
    setDraft(value ?? '');
    setEditing(true);
  };

  if (!editing && trigger === 'pencil') {
    return (
      <span className={cn('inline-flex max-w-full items-center gap-1', className)}>
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {shown ?? <span className="text-ink-3">{placeholder}</span>}
        </span>
        <button
          ref={buttonRef}
          type="button"
          aria-label={`Edit ${label}`}
          onClick={open}
          className="shrink-0 rounded p-1 text-ink-4 transition-colors duration-quick hover:bg-sunken hover:text-ink"
        >
          <Icon.edit size={13} aria-hidden />
        </button>
      </span>
    );
  }

  if (!editing) {
    return (
      <button
        ref={buttonRef}
        type="button"
        aria-label={`Edit ${label}`}
        onClick={open}
        className={cn(
          'group -mx-1.5 inline-flex max-w-full items-center gap-1.5 rounded px-1.5 py-0.5 text-left text-ink',
          'transition-colors duration-quick hover:bg-sunken',
          className,
        )}
      >
        <span className="min-w-0 [overflow-wrap:anywhere]">
          {shown ?? <span className="text-ink-3">{placeholder}</span>}
        </span>
        <Icon.edit
          size={13}
          aria-hidden
          className="shrink-0 text-ink-4 opacity-0 transition-opacity duration-quick group-hover:opacity-100 group-focus-visible:opacity-100"
        />
      </button>
    );
  }

  const fieldClass = cn('input h-8 py-1', error && 'border-negative focus:border-negative focus:ring-negative');
  const common = {
    'aria-label': label,
    'aria-invalid': error ? true : undefined,
    'aria-describedby': error ? errorId : undefined,
    disabled: pending,
  } as const;

  return (
    <span className={cn('inline-flex w-full max-w-sm flex-col', className)}>
      {kind === 'select' ? (
        <select
          ref={fieldRef}
          {...common}
          className={cn(fieldClass, 'pr-8')}
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            void save(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === 'Escape') {
              event.preventDefault();
              close();
            }
          }}
          onBlur={() => {
            if (!pending && !error) close();
          }}
        >
          {options?.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      ) : (
        <input
          ref={fieldRef}
          {...common}
          type={kind === 'number' ? 'number' : 'text'}
          placeholder={inputPlaceholder}
          inputMode={kind === 'number' ? 'numeric' : undefined}
          className={fieldClass}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') {
              event.preventDefault();
              void save(draft);
            } else if (event.key === 'Escape') {
              event.preventDefault();
              close();
            }
          }}
          onBlur={() => {
            if (!pending && !error) void save(draft);
          }}
        />
      )}
      {pending && <span className="mt-1 text-caption text-ink-3">Saving…</span>}
      {error && (
        <span id={errorId} role="alert" className="mt-1 text-caption text-negative">
          {error}
        </span>
      )}
    </span>
  );
}
