import { defineConfig } from '@playwright/test'

const production = process.env.PLAYWRIGHT_PRODUCTION === '1'
const port = production ? 4174 : 5174

export default defineConfig({
 testDir: './tests',
 workers: 1,
 use: {
  baseURL: `http://127.0.0.1:${port}`,
  browserName: 'chromium',
  viewport: { width: 1440, height: 1000 },
  locale: 'en-US',
  timezoneId: 'Asia/Almaty',
  colorScheme: 'light',
  trace: 'retain-on-failure',
 },
 webServer: [
  {
   command: '../backend/.venv/bin/python -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8002',
   url: 'http://127.0.0.1:8002/health',
   env: { CATALOG_PATH: 'hackathon dataset anonymized .csv', CATALOG_ORIGIN: 'original' },
   reuseExistingServer: false,
   timeout: 60_000,
  },
  {
   command: production ? 'npm run preview -- --host 127.0.0.1 --port 4174 --strictPort' : 'npm run dev -- --port 5174 --strictPort',
   url: `http://127.0.0.1:${port}`,
   env: { API_PROXY_TARGET: 'http://127.0.0.1:8002' },
   reuseExistingServer: false,
   timeout: 60_000,
  },
 ],
})
