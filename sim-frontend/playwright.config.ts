import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  // The V6 scripts remain available for its frozen UI and selector vocabulary.
  testMatch: process.env.E2E_PROFILE === 'legacy' ? /^(?!.*v7-delivery).*\.spec\.ts$/ : '**/v7-delivery.spec.ts',
  timeout: 30000,
  retries: 0,
  fullyParallel: false,
  workers: 1,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://127.0.0.1:5173',
    headless: true,
    viewport: { width: 1600, height: 900 },
  },
})
