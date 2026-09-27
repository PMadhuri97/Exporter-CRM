import { Kanban, LayoutDashboard, ListChecks, Users } from 'lucide-react';
import { NavLink } from 'react-router-dom';

interface NavItem {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
  /** Screens not built yet render as a disabled row with a "Soon" badge —
   * never a link to a route that renders nothing, per the design principle
   * against fake navigation. */
  status: 'ready' | 'soon';
}

// One row per later ticket in docs/exporter-crm-frontend-tickets.md's build
// sequence — flip `status` to 'ready' as each ticket lands, rather than
// adding the row from scratch.
const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard', path: '/', icon: LayoutDashboard, status: 'ready' },
  { label: 'Exporters', path: '/exporters', icon: Users, status: 'ready' },
  {
    label: 'Follow-ups',
    // `status` flips to 'ready' in the same commit as `pages/FollowUpsPage.tsx`, per
    // that ticket's rule: not before (dead navigation) and not after (a shipped page
    // nobody can reach). `path` moves with it — the screen lives inside the
    // onboarding module's own subtree, which is mounted at `/exporters/*`, so
    // `/follow-ups` would resolve to nothing. See `modules/onboarding/routes.tsx`
    // for why the route is there rather than in the app router.
    path: '/exporters/follow-ups',
    icon: ListChecks,
    status: 'ready',
  },
  { label: 'Pipeline', path: '/pipeline', icon: Kanban, status: 'ready' },
  // ══ Section 9.3 — anchor blocks for Developers 3A and 3B ══════════════════
  //
  // The seam commit cuts the tail of this list into owned blocks so that three
  // people adding rows — 3A in each of its two phases, and 3B — never share a
  // hunk. The `Follow-ups` row above already exists; **Phase 2** flips its one
  // word (`status: 'soon'` -> `'ready'`) when the screen lands, which is a
  // different line from anything below, so there is no conflict either way.
  //
  // ── Conversation and follow-ups — owner: Developer 3A (L3-02 … L3-04) ──
  // (3A appends here; 3B does not.) Cut into the two phase sub-anchors below —
  // phase agreement §6.3. Phase 1 adds no row: the conversation gauge is a panel
  // on the company page, which `Exporters` already reaches.
  //
  // ── 3A·1 Conversation gauge (L3-02, L3-03) — Phase 1 appends here ──
  //
  // ── 3A·2 Follow-ups (L3-04) — Phase 2 appends here ──
  //
  // ── Deals, buyers, storage and documents — owner: Developer 3B (L3-05 … L3-10) ──
  // (3B appends here; 3A does not.)
];

export function Sidebar() {
  return (
    <nav className="flex w-60 shrink-0 flex-col border-r border-border bg-surface px-3 py-5">
      <div className="mb-6 flex items-center gap-2 px-2">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-sm font-semibold text-brand-400">
          A
        </div>
        <div>
          <p className="text-sm font-semibold text-ink">ANER</p>
          <p className="text-xs text-ink-faint">Exporter CRM</p>
        </div>
      </div>

      <ul className="flex flex-1 flex-col gap-0.5">
        {NAV_ITEMS.map((item) => (
          <li key={item.path}>
            {item.status === 'ready' ? (
              <NavLink
                to={item.path}
                end={item.path === '/'}
                className={({ isActive }) =>
                  `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                    isActive
                      ? 'bg-brand-50 text-brand-600'
                      : 'text-ink-muted hover:bg-surface-sunken hover:text-ink'
                  }`
                }
              >
                <item.icon size={17} strokeWidth={2} />
                {item.label}
              </NavLink>
            ) : (
              <div
                className="flex items-center justify-between gap-2.5 rounded-lg px-3 py-2 text-sm font-medium text-ink-faint"
                aria-disabled="true"
              >
                <span className="flex items-center gap-2.5">
                  <item.icon size={17} strokeWidth={2} />
                  {item.label}
                </span>
                <span className="rounded-full bg-surface-sunken px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-ink-faint">
                  Soon
                </span>
              </div>
            )}
          </li>
        ))}
      </ul>
    </nav>
  );
}
