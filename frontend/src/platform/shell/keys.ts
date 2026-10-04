/**
 * Keyboard helpers shared by the shell and pages (frontend-plan §7.4).
 * Shortcuts never fire while someone is typing.
 */

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  const tag = target.tagName;
  if (tag === 'TEXTAREA' || tag === 'SELECT') return true;
  if (tag === 'INPUT') {
    const type = (target as HTMLInputElement).type;
    return !['button', 'checkbox', 'radio', 'submit', 'reset'].includes(type);
  }
  // A cmdk list or a Radix menu owns its own keys.
  return target.closest('[cmdk-root], [role="menu"], [role="listbox"]') !== null;
}

/** Whether a key event carries a modifier that turns it into something else. */
export function hasModifier(event: KeyboardEvent): boolean {
  return event.altKey || event.ctrlKey || event.metaKey;
}

/** "Ctrl" or "⌘" for the command-bar hint, by platform. */
export function commandKeyLabel(): string {
  const platform =
    typeof navigator === 'undefined'
      ? ''
      : ((navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ??
        navigator.platform ??
        '');
  return /mac|iphone|ipad/i.test(platform) ? '⌘' : 'Ctrl';
}
