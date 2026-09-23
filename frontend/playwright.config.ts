import { defineConfig } from '@playwright/test'

export default defineConfig({
 testDir: './tests',
 workers: 1,
 use: {
  baseURL: 'http://127.0.0.1:5174',
  browserName: 'chromium',
  trace: 'retain-on-failure',
 },
 webServer: [
  {
   command: '../backend/.venv/bin/python -m uvicorn app.main:app --app-dir ../backend --host 127.0.0.1 --port 8002',
   url: 'http://127.0.0.1:8002/health',
   reuseExistingServer: false,
   timeout: 60_000,
  },
  {
   command: 'npm run dev -- --port 5174 --strictPort',
   url: 'http://127.0.0.1:5174',
   env: { API_PROXY_TARGET: 'http://127.0.0.1:8002' },
   reuseExistingServer: false,
   timeout: 60_000,
  },
 ],
})
