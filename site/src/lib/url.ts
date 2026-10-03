/** Prefix a site path with the configured base (GitHub Pages lives under /<repo>/). */
export function href(path = ''): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  const p = path.replace(/^\//, '');
  return `${base}/${p}`;
}
