/**
 * Whether a stored value is a web link that is safe to render as `href`: an absolute
 * `http:` or `https:` URL with a host. React 18 does not block a `javascript:` href,
 * so anything else — including a value stored before the server refused it — must be
 * shown as text, never as a link.
 *
 * The same rule as the server's `domain/web_links.py`, used for a company's website
 * and a verification result's `url` evidence.
 */
export function isWebLink(value: string): boolean {
  try {
    const url = new URL(value);
    return (url.protocol === 'http:' || url.protocol === 'https:') && url.host !== '';
  } catch {
    return false;
  }
}
