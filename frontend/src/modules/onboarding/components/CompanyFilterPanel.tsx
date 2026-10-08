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

import { COUNTRY_OPTIONS } from '../countries';

import type {
  BackgroundCheckState,
  CompanyPipelineStatus,
  CompanyTradeRole,
  ExporterSource,
} from '../types';

/** How long typing must stop before the industry filter is sent. */
const TYPING_SETTLES_MS = 350;

/** The filters this panel owns. A key is absent when it is not filtering. */
export interface CompanyFilters {
  source?: ExporterSource;
  pipeline_status?: CompanyPipelineStatus;
  background_check?: BackgroundCheckState;
  trade_role?: CompanyTradeRole;
  has_open_deals?: boolean;
  country?: string;
  industry?: string;
}

/**
 * The sources worth filtering by, not every value the enum holds.
 *
 * `ExporterSource` also has `PARTNER`, `API`, `BROKER`, `EVENT` and `DEAL_BUYER`. They
 * stay valid on the server — a company already carrying one keeps it, and the API still
 * accepts it — they are simply not offered here, because a filter nobody picks is a
 * longer list to read past. `DEAL_BUYER` in particular is better asked as *Buyer or
 * seller*, which answers by what the company has done rather than how its record began.
 *
 * A `Partial` record on purpose: adding a sixth source to the enum should not silently
 * appear in this list, and leaving one out should not be a type error.
 */
const SOURCE_LABEL: Partial<Record<ExporterSource, string>> = {
  MANUAL: 'Manual entry',
  SALES: 'Sales',
  REFERRAL: 'Referral',
  RXIL: 'RXIL',
  EXISTING_CUSTOMER: 'Existing customer',
};

const CHECK_LABEL: Record<BackgroundCheckState, string> = {
  NOT_STARTED: 'Not started',
  IN_REVIEW: 'In review',
  CLEAR: 'Clear',
  MORE_INFO: 'More information needed',
  FLAGGED: 'Flagged',
  ON_HOLD: 'On hold',
};

const ROLE_LABEL: Record<CompanyTradeRole, string> = {
  SELLER: 'Seller',
  BUYER: 'Buyer',
  BOTH: 'Both',
};

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

export function CompanyFilterPanel({
  applied,
  shown,
  loading,
  onChange,
  onClose,
}: {
  /** The filters in force; the controls read from these. */
  applied: CompanyFilters;
  /** How many companies the current filters return, for the running count. */
  shown: number;
  loading: boolean;
  /**
   * Must be referentially stable — the typing timer below depends on it, and a new
   * function each render would restart the timer on every render and never fire.
   */
  onChange: Dispatch<SetStateAction<CompanyFilters>>;
  onClose: () => void;
}) {
  const [industry, setIndustry] = useState(applied.industry ?? '');

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

  const count = Object.keys(applied).length;

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
          {loading ? 'Counting…' : `${shown} ${shown === 1 ? 'company' : 'companies'} shown`}
        </p>

        {choice('source', 'Source', SOURCE_LABEL, 'How the company first reached us.')}
        {/* No hint under this one. It reads by participation, and asking for buyers
            lifts the list's buyer-only exclusion — both true, both explained in the
            route's own description, and neither worth a paragraph beside a dropdown. */}
        {choice('trade_role', 'Buyer or seller', ROLE_LABEL)}
        {choice('background_check', 'Background check', CHECK_LABEL)}

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
            {COUNTRY_OPTIONS.map(({ code, name }) => (
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
      </div>
    </Sheet>
  );
}
