/**
 * The Companies list's extra filters, in a panel behind one *Filters* button.
 *
 * Not in the filter bar: there are seven of them, and inline they would make the
 * controls taller than the first row of results. The bar keeps the three used on almost
 * every visit (journey, qualification, relationship); the rest live here.
 *
 * **The list follows as you choose** — there is no Apply. Picking a value filters at
 * once, so the panel can stay open while someone narrows the list and watches it
 * change. The count beside the title is the server's answer to what is set so far.
 *
 * That costs a request per change, which is affordable for the selects: each is one
 * click, and a click is already a request's worth of thinking. It is *not* affordable
 * per keystroke, so the only free-text filter — industry — is held back until typing
 * stops (`TYPING_SETTLES_MS`).
 *
 * Every value here is a server filter (`GET /onboarding/exporters`). Nothing is
 * narrowed in the browser, so a filtered list is the server's answer and the counts
 * beside it stay true.
 *
 * The page mounts this only while it is open, so each opening starts from the filters
 * actually in force and there is no stale draft to reconcile.
 */

import { useEffect, useState, type Dispatch, type SetStateAction } from 'react';

import { Button, Input, Select, Sheet } from '@/components';
import { useCan } from '@/platform/access';

// One country list, shared with the company form's own picker.
import { countryOptions } from '../countries';
import {
  CHECK_LABEL,
  ROLE_LABEL,
  SOURCE_LABEL,
  type CompanyFilters,
} from '../companyFilters';

/** How long typing must stop before the industry filter is sent. */
const TYPING_SETTLES_MS = 350;


/** `filters` with `key` set, or removed when the value is cleared — so the object only
 * ever holds filters that are filtering, which is what the page counts for its badge. */
function withValue<K extends keyof CompanyFilters>(
  filters: CompanyFilters,
  key: K,
  value: CompanyFilters[K],
): CompanyFilters {
  const next = { ...filters };
  if (value === undefined || value === '') delete next[key];
  else next[key] = value;
  return next;
}

/**
 * The three filters that live in the URL rather than in `CompanyFilters`.
 *
 * `?owner=`, `?contact=` and `?collections=` are lenses: a link to one can be shared,
 * and *My companies* is `?owner=me` with its own row in the side navigation. They are
 * shown here with the rest so the bar holds the few used on every visit, but they keep
 * their own state — folding them into `CompanyFilters` would change what a shared link
 * means.
 */
export interface CompanyLenses {
  owner: string;
  contacts: string;
  collections: string;
}

const LENS_LABEL: Record<keyof CompanyLenses, string> = {
  owner: 'Owner',
  contacts: 'Contacts',
  collections: 'Collections owner',
};

/** What each lens offers, after its own "Any". */
const LENS_OPTIONS: Record<keyof CompanyLenses, { value: string; label: string }[]> = {
  owner: [
    { value: 'none', label: 'Unassigned' },
    { value: 'inactive', label: 'RM deactivated' },
  ],
  contacts: [{ value: 'missing', label: 'No primary contact' }],
  collections: [
    { value: 'me', label: 'My collections' },
    { value: 'none', label: 'No collections owner' },
  ],
};

export function CompanyFilterPanel({
  applied,
  lenses,
  shown,
  loading,
  onChange,
  onLensChange,
  onClose,
}: {
  /** The filters in force; the controls read from these. */
  applied: CompanyFilters;
  /**
   * How many companies the filters match — the server's count, not the length of the
   * page on screen. The two differ by a page size, which is how "50 shown" appeared
   * against a filter matching 185.
   */
  /**
   * The URL-backed lenses. `owner` is absent from the panel on *My companies*, where
   * the page itself is the lens and a second way to say it would contradict the title.
   */
  lenses: CompanyLenses;
  shown: number;
  loading: boolean;
  /**
   * Must be referentially stable — the typing timer below depends on it, and a new
   * function each render would restart the timer on every render and never fire.
   */
  onChange: Dispatch<SetStateAction<CompanyFilters>>;
  /** `'ANY'` clears a lens, matching what the URL state treats as not filtering. */
  onLensChange: (key: keyof CompanyLenses, value: string) => void;
  onClose: () => void;
}) {
  const [industry, setIndustry] = useState(applied.industry ?? '');
  // The server refuses `?background_check=` from a role that may not read a
  // background check — they are not shown to DEVELOPER — so offering the filter here
  // would only produce a 403.
  const canReadChecks = useCan('compliance.read');

  // Sent once typing stops, not per keystroke. Cleared on the next change, so only the
  // last pause sends; skipped when it already matches, so re-renders send nothing.
  useEffect(() => {
    const value = industry.trim() || undefined;
    const timer = setTimeout(() => {
      onChange((previous) =>
        previous.industry === value ? previous : withValue(previous, 'industry', value),
      );
    }, TYPING_SETTLES_MS);
    return () => clearTimeout(timer);
  }, [industry, onChange]);

  const set = <K extends keyof CompanyFilters>(key: K, value: CompanyFilters[K]) =>
    onChange((previous) => withValue(previous, key, value));

  /** A select whose empty option means "not filtering on this". */
  const choice = <K extends keyof CompanyFilters>(
    key: K,
    label: string,
    options: Partial<Record<string, string>>,
    hint?: string,
  ) => (
    <label className="block text-caption font-medium text-ink-2">
      {label}
      <Select
        aria-label={label}
        className="mt-1"
        value={(applied[key] as string | undefined) ?? ''}
        onChange={(event) => set(key, (event.target.value || undefined) as CompanyFilters[K])}
      >
        <option value="">Any</option>
        {Object.entries(options).map(([value, text]) => (
          <option key={value} value={value}>
            {text}
          </option>
        ))}
      </Select>
      {hint && <span className="mt-1 block font-normal text-ink-3">{hint}</span>}
    </label>
  );

  // `owner: 'me'` is My companies, the page itself — not a filter on it. Counting it
  // would badge that page as narrowed on arrival, and clearing it would move the
  // viewer to a different page rather than widening the one they are reading.
  const setLenses = (Object.keys(LENS_LABEL) as (keyof CompanyLenses)[]).filter(
    (key) => lenses[key] !== 'ANY' && !(key === 'owner' && lenses.owner === 'me'),
  );
  const count = Object.keys(applied).length + setLenses.length;

  return (
    <Sheet
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
      title="Filters"
      description="The list follows as you choose."
      footer={
        <div className="flex items-center justify-between gap-2">
          <Button
            size="sm"
            variant="subtle"
            disabled={count === 0}
            onClick={() => {
              setIndustry('');
              onChange({});
              for (const key of setLenses) onLensChange(key, 'ANY');
            }}
          >
            Clear all
          </Button>
          {/* The list is already filtered — choices take effect as they are made — so
              this closes the panel. "Apply" is what people reach for, and reading it as
              "apply and close" is true of what happens. */}
          <Button size="sm" variant="primary" onClick={onClose}>
            Apply
          </Button>
        </div>
      }
    >
      <div className="flex flex-col gap-4 p-4">
        {/* What the filters are doing, without closing the panel to find out. */}
        <p aria-live="polite" className="text-secondary text-ink-2">
          {loading
            ? 'Counting…'
            : `${shown} ${shown === 1 ? 'company' : 'companies'} match`}
        </p>

        {choice('source', 'Source', SOURCE_LABEL, 'How the company first reached us.')}
        {/* No hint under this one. It reads by participation, and asking for buyers
            lifts the list's buyer-only exclusion — both true, both explained in the
            route's own description, and neither worth a paragraph beside a dropdown. */}
        {choice('trade_role', 'Buyer or seller', ROLE_LABEL)}
        {canReadChecks && choice('background_check', 'Background check', CHECK_LABEL)}

        <label className="block text-caption font-medium text-ink-2">
          Deals
          <Select
            aria-label="Deals"
            className="mt-1"
            value={applied.has_open_deals === undefined ? '' : String(applied.has_open_deals)}
            onChange={(event) =>
              set(
                'has_open_deals',
                event.target.value === '' ? undefined : event.target.value === 'true',
              )
            }
          >
            <option value="">Any</option>
            {/* The condition joins the deal's selling company, so this reads by the
                company's own deals. Whether it should count the buying side too is
                still open. */}
            <option value="true">Has an open deal</option>
            <option value="false">No open deal</option>
          </Select>
        </label>

        <label className="block text-caption font-medium text-ink-2">
          Country
          <Select
            aria-label="Country"
            className="mt-1"
            value={applied.country ?? ''}
            onChange={(event) => set('country', event.target.value || undefined)}
          >
            <option value="">Any</option>
            {countryOptions().map(({ code, name }) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </Select>
        </label>

        <label className="block text-caption font-medium text-ink-2">
          Industry
          <Input
            aria-label="Industry"
            className="mt-1"
            value={industry}
            placeholder="e.g. Textiles"
            onChange={(event) => setIndustry(event.target.value)}
          />
          <span className="mt-1 block font-normal text-ink-3">
            Matches any part of the industry, so &ldquo;ma&rdquo; finds &ldquo;Marine exports&rdquo;.
          </span>
        </label>

        {/* Who holds the company, and what it is missing. Last because they answer
            "whose work is this" rather than "what kind of company is this", which is
            what everything above asks. */}
        {(Object.keys(LENS_LABEL) as (keyof CompanyLenses)[]).map((key) =>
          // On My companies the owner is the page itself.
          key === 'owner' && lenses.owner === 'me' ? null : (
            <label key={key} className="block text-caption font-medium text-ink-2">
              {LENS_LABEL[key]}
              <Select
                aria-label={LENS_LABEL[key]}
                className="mt-1"
                value={lenses[key] === 'ANY' ? '' : lenses[key]}
                onChange={(event) => onLensChange(key, event.target.value || 'ANY')}
              >
                <option value="">Any</option>
                {LENS_OPTIONS[key].map(({ value, label }) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </Select>
            </label>
          ),
        )}
      </div>
    </Sheet>
  );
}
