/**
 * The reader's name and the time, repeated faintly across a document on screen.
 *
 * A screenshot of a watermarked page names who took it and when; that is what makes
 * "read on screen, do not save" worth asking for, since nothing in a browser can stop
 * a screenshot. The mark is a repeating SVG background, so it covers a page of any
 * height, and it ignores the pointer so the document underneath stays readable and
 * scrollable.
 */

function escapeXml(text: string): string {
  return text
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&apos;');
}

/** The tile, as a data URL: the text once, rotated. */
function watermarkTile(text: string): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" width="360" height="200">` +
    `<text x="20" y="120" transform="rotate(-24 180 100)" font-family="Segoe UI, Arial, sans-serif" ` +
    `font-size="15" fill="#64748b" fill-opacity="0.22">${escapeXml(text)}</text></svg>`;
  return `url("data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}")`;
}

export function DocumentWatermark({ text }: { text: string }) {
  return (
    <div
      aria-hidden
      data-testid="document-watermark"
      data-text={text}
      className="pointer-events-none absolute inset-0 z-10"
      style={{ backgroundImage: watermarkTile(text), backgroundRepeat: 'repeat' }}
    />
  );
}
