/**
 * One-click credential fill for the seeded demo accounts.
 *
 * **This never reaches a production build.** `import.meta.env.DEV` is replaced by a
 * literal `false` by Vite when it builds for production, so the early return becomes
 * `if (true) return null` and the whole component — including the passwords below —
 * is removed by tree-shaking. The strings are not in `dist/`; they are not hidden
 * there behind a flag.
 *
 * That is the only reason it is safe to write a password in a page like this, and it
 * is why the check is a build-time constant rather than a runtime setting such as a
 * feature flag or an environment variable read at startup: a runtime check would ship
 * the credentials and merely decline to show them.
 *
 * The accounts are the five created by `cli bootstrap` plus sign-up — one per role.
 * If the seeded passwords change, change them here; nothing reads them from the
 * server, because the server will not hand out passwords and should not.
 */

const DEMO_PASSWORD = 'Passw0rd123';

interface DemoAccount {
  role: string;
  email: string;
  /** What this login is for, so a demo can pick the right one without guessing. */
  note: string;
}

const ACCOUNTS: DemoAccount[] = [
  { role: 'Admin', email: 'admin@aner.example', note: 'Everything, plus users and criteria' },
  { role: 'Compliance', email: 'compliance@aner.example', note: 'Clears, flags, screens. Sees full PAN' },
  { role: 'Operations', email: 'operations@aner.example', note: 'Day-to-day CRM. PAN masked' },
  { role: 'Developer', email: 'developer@aner.example', note: 'Read-only. No background check at all' },
  { role: 'API user', email: 'api@aner.example', note: 'Signs in, but reaches nothing' },
];

export function DemoAccounts({
  onPick,
}: {
  /** Fills the form. The person still presses Sign in, so the form is visible. */
  onPick: (email: string, password: string) => void;
}) {
  if (!import.meta.env.DEV) return null;

  return (
    <aside
      aria-label="Demo accounts"
      className="w-full rounded-xl border border-dashed border-border bg-surface p-5 sm:-mt-28 sm:w-72"
    >
      {/* `sm:-mt-28` above lifts the panel into the empty space beside the
          "Sign in to ANER" heading, which is otherwise wasted: this panel is
          taller than the form, so top-aligning the two left it hanging well
          below. From `sm` up only — on a narrow screen the panel stacks under
          the form, where a negative offset would drag it over the button.
          No `mt` on the list: the heading it used to sit below is gone. */}
      <ul className="flex flex-col gap-1.5">
        {ACCOUNTS.map((account) => (
          <li key={account.email}>
            <button
              type="button"
              onClick={() => onPick(account.email, DEMO_PASSWORD)}
              className="w-full rounded-lg border border-border px-3 py-2 text-left transition-colors hover:border-brand-600 hover:bg-brand-50"
            >
              <span className="block text-sm font-medium text-ink">{account.role}</span>
              <span className="block truncate text-xs text-ink-muted">{account.email}</span>
              <span className="mt-0.5 block text-[11px] leading-snug text-ink-faint">
                {account.note}
              </span>
            </button>
          </li>
        ))}
      </ul>

      
    </aside>
  );
}
