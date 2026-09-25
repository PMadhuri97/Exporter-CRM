/**
 * Deals — **owner: Developer 3** (architecture §9.3, tasks L3-05 to L3-11).
 *
 * A seam, not a feature. Deals do not exist yet: there is no deal table
 * (migration 0018 is Developer 3's), no deal route and no deal type. This file
 * exists so that when Developer 3 builds them, the panel already has a place
 * on the page and an owner, and the shell does not have to change.
 *
 * **It renders nothing, on purpose.** The rule for this phase was that a
 * mechanical split must not change what the page looks like, and a placeholder
 * reading "Deals — coming soon" would be a new visible section nobody asked
 * for. `null` keeps the DOM identical to before the split while still giving
 * Developer 3 a one-file change to make.
 *
 * Same reasoning the sidebar uses for its unbuilt screens: never show a link
 * to something that renders nothing. Here, show nothing at all until there is
 * something to show.
 */

export function DealsPanel(_props: { customerId: string; isStaff: boolean }) {
  return null;
}
