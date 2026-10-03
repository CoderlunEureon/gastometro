// @ts-check
import { defineConfig } from 'astro/config';

// On GitHub Pages the site lives under /<repo>/. Both values come from the
// workflow (SITE_URL / BASE_PATH) and default to a local build at "/".
export default defineConfig({
  site: process.env.SITE_URL || 'https://example.github.io',
  base: process.env.BASE_PATH || '/',
  trailingSlash: 'ignore',
  build: { format: 'directory' },
});
