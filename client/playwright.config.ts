import { defineConfig, devices } from '@playwright/test';

// Runs the static demo end to end. Set BASE_URL to test a deployed copy;
// without it, Playwright serves the local demo build (npm run build:demo).
// PW_CHANNEL=chrome uses the installed Google Chrome instead of the bundled browser.
const baseURL = process.env.BASE_URL || 'http://localhost:4173';

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: 0,
  reporter: [['list']],
  use: { baseURL, ...devices['Desktop Chrome'], viewport: { width: 1280, height: 800 }, channel: process.env.PW_CHANNEL || undefined },
  webServer: process.env.BASE_URL
    ? undefined
    : { command: 'npx vite preview --outDir dist --port 4173 --strictPort', url: baseURL, reuseExistingServer: false },
});
