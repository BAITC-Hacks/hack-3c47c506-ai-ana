import { test, expect, type Page } from '@playwright/test'
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { platform, release, arch, cpus } from 'node:os'
import type { RecommendationRequest, RecommendationResponse } from '../src/lib/api/generated'
import { artifactPrefix } from './artifacts'

type Baseline = {
 scenario: string
 status: RecommendationResponse['status']
 catalog_version: string
 ranking_version: string
 counts: RecommendationResponse['counts']
 eligible_ids: string[]
 profiles: { id: string }[]
}

type BrowserSample = {
 key: string
 submitted_at_ms: number | null
 fetch_started_at_ms: number | null
 json_ready_at_ms: number | null
 rendered_at_ms: number | null
 response: RecommendationResponse | null
 render_pending: boolean
}

declare global {
 interface Window {
  __stage7Probe: { current: BrowserSample | null; arm: (key: string) => void }
 }
}

const docs = new URL('../../docs/', import.meta.url)
const baseline = JSON.parse(readFileSync(new URL('matching-report.json', docs), 'utf8')) as { results: Baseline[] }
const scenarios = [
 'corporate-host', 'corporate-host-next-date', 'rare-category',
 'no-matches', 'no-category', 'venue-free', 'venue-busy',
]
const button = (page: Page) => page.getByRole('button', { name: /^(Подобрать подрядчиков|Обновить подбор)$/ })

async function fillQuery(page: Page, query: RecommendationRequest) {
 const fields = [
  { label: 'Город', value: query.city, select: true },
  { label: 'Кого ищем', value: query.category, select: true },
  { label: 'Дата события', value: query.event_date, select: false },
  { label: 'Формат', value: query.event_format, select: true },
  { label: 'Бюджет, ₸', value: String(query.budget_kzt), select: false },
  { label: 'Длительность, ч', value: query.duration_hours == null ? '' : String(query.duration_hours), select: false },
  { label: 'Язык', value: query.language ?? '', select: true },
 ]
 let changed = false
 for (const field of fields) {
  const control = page.getByLabel(field.label, { exact: true })
  if (await control.inputValue() === field.value) continue
  changed = true
  if (field.select) await control.selectOption(field.value)
  else await control.fill(field.value)
 }
 return changed
}

async function waitForAutomaticResult(page: Page, query: RecommendationRequest, expected: Baseline) {
 const context = [
  query.city, query.category, query.event_format.charAt(0).toUpperCase() + query.event_format.slice(1),
  query.event_date.split('-').reverse().join('.'), `${query.budget_kzt.toLocaleString('ru-RU')} ₸`,
  query.duration_hours ? `${Number(query.duration_hours).toLocaleString('ru-RU')} ч` : null, query.language,
 ].filter(Boolean).join(' · ')
 // Waiting for the final rendered query also waits through debounce and any
 // intermediate requests made while the seven controls were being filled.
 await expect(page.locator('.results [aria-live="polite"]')).toHaveAttribute('aria-busy', 'false')
 await expect(page.locator('.example-context')).toHaveText(`Условия подбора: ${context}`)
 await expect.poll(() => page.locator('.contractor-card').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id'))))
  .toEqual(expected.profiles.map(profile => profile.id))
 if (expected.status === 'MATCHED') await expect(page.locator('.result-summary')).toBeVisible()
 else await expect(page.locator(`.result-state[data-status="${expected.status}"]`)).toBeVisible()
}

function statistics(values: number[]) {
 const sorted = [...values].sort((a, b) => a - b)
 const percentile = (p: number) => sorted[Math.ceil(p * sorted.length) - 1]
 return {
  samples: values.length,
  raw_ms: values,
  min_ms: sorted[0], max_ms: sorted[sorted.length - 1],
  mean_ms: values.reduce((sum, value) => sum + value, 0) / values.length,
  p50_ms: percentile(0.5), p95_ms: percentile(0.95),
 }
}

test('семь сценариев из исходного каталога и повторяемость с браузерными замерами', async ({ page, browser, browserName, baseURL }) => {
 test.skip(process.env.PLAYWRIGHT_PRODUCTION !== '1', 'Замеры и отчёт предназначены только для production preview.')
 test.setTimeout(120_000)
 const pageErrors: string[] = []
 page.on('pageerror', error => pageErrors.push(error.message))
 await page.setViewportSize({ width: 1440, height: 1000 })

 // The clock starts on the actual browser submit event, not before a Playwright
 // action. Response.json is observed without a second request or clone parsing.
 // The DOM observer waits for matching cards/state, then two animation frames.
 await page.addInitScript(() => {
  window.__stage7Probe = {
   current: null,
   arm(key) {
    this.current = {
     key, submitted_at_ms: null, fetch_started_at_ms: null,
     json_ready_at_ms: null, rendered_at_ms: null,
     response: null, render_pending: false,
    }
   },
  }
  document.addEventListener('submit', event => {
   const sample = window.__stage7Probe.current
   if (sample && event.target instanceof HTMLFormElement && event.target.closest('.form-panel')) {
    sample.submitted_at_ms = performance.now()
   }
  }, true)
  const fetchOriginal = window.fetch.bind(window)
  window.fetch = async (input, init) => {
   const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.href)
   const method = init?.method ?? (input instanceof Request ? input.method : 'GET')
   const sample = url.pathname === '/api/recommendations' && method.toUpperCase() === 'POST'
    ? window.__stage7Probe.current : null
   if (sample) sample.fetch_started_at_ms = performance.now()
   const response = await fetchOriginal(input, init)
   if (sample) {
    const jsonOriginal = response.json.bind(response)
    response.json = async () => {
     const payload = await jsonOriginal()
     sample.json_ready_at_ms = performance.now()
     sample.response = payload
     return payload
    }
   }
   return response
  }
  function isRendered(sample: BrowserSample) {
   if (!sample.response || sample.submitted_at_ms === null || sample.json_ready_at_ms === null) return false
   const region = document.querySelector('.results [aria-live="polite"]')
   if (!region || region.getAttribute('aria-busy') !== 'false') return false
   const query = sample.response.query
   const context = region.querySelector('.example-context')?.textContent ?? ''
   const expectedContext = [
    query.city, query.category, query.event_format.charAt(0).toUpperCase() + query.event_format.slice(1),
    query.event_date.split('-').reverse().join('.'), `${query.budget_kzt.toLocaleString('ru-RU')} ₸`,
    query.duration_hours ? `${Number(query.duration_hours).toLocaleString('ru-RU')} ч` : null, query.language,
   ].filter(Boolean).join(' · ')
   if (context !== `Условия подбора: ${expectedContext}`) return false
   const ids = [...region.querySelectorAll('.contractor-card')].map(card => card.getAttribute('data-profile-id'))
   if (JSON.stringify(ids) !== JSON.stringify(sample.response.cards.map(card => card.id))) return false
   if (sample.response.status === 'MATCHED') return !!region.querySelector('.result-summary')
   return !!region.querySelector(`.result-state[data-status="${sample.response.status}"]`)
  }
  new MutationObserver(() => {
   const sample = window.__stage7Probe.current
   if (!sample || sample.render_pending || sample.rendered_at_ms !== null || !isRendered(sample)) return
   sample.render_pending = true
   requestAnimationFrame(() => requestAnimationFrame(() => {
    sample.render_pending = false
    if (window.__stage7Probe.current !== sample || !isRendered(sample)) return
    // Force layout before the final timestamp; this is a render proxy, not a
    // claim that every pixel was presented by the operating system compositor.
    document.querySelector('.results')!.getBoundingClientRect()
    sample.rendered_at_ms = performance.now()
   }))
  }).observe(document, { subtree: true, childList: true, attributes: true, characterData: true })
 })

 await page.goto('/')
 await expect(button(page)).toBeEnabled()
 await page.evaluate(() => document.fonts.ready)
 await expect(page.locator('.demo-banner')).toContainText('Исходный каталог')
 const performanceTimeOrigin = await page.evaluate(() => performance.timeOrigin)
 const userAgent = await page.evaluate(() => navigator.userAgent)
 const samples: Array<{
  scenario: string
  kind: 'scenario' | 'warm-repeat'
  query: RecommendationRequest
  normalized_query: RecommendationResponse['query']
  status: RecommendationResponse['status']
  ids: string[]
  counts: RecommendationResponse['counts']
  catalog_version: string
  ranking_version: string
  explanation_version: string
  timing: {
   submit_to_render_ms: number
   fetch_to_json_ms: number
   json_to_render_ms: number
   raw: Omit<BrowserSample, 'response' | 'render_pending'>
  }
 }> = []
 let original: RecommendationResponse | undefined
 mkdirSync(new URL('screenshots/', docs), { recursive: true })

 async function runScenario(scenario: string, kind: 'scenario' | 'warm-repeat', repetition = 0) {
  const expected = baseline.results.find(result => result.scenario === scenario)
  expect(expected, `Эталон для ${scenario}`).toBeDefined()
  const query = JSON.parse(readFileSync(new URL(`queries/${scenario}.json`, docs), 'utf8')) as RecommendationRequest
  await page.evaluate(() => { window.__stage7Probe.current = null })
  const changed = await fillQuery(page, query)
  // Initial defaults and identical warm repeats do not cause an automatic search.
  if (changed) await waitForAutomaticResult(page, query, expected!)
  await page.evaluate(key => window.__stage7Probe.arm(key), `${scenario}:${repetition}`)
  const httpResponse = page.waitForResponse(response => response.url().endsWith('/api/recommendations') && response.request().method() === 'POST')
  await button(page).click()
  const response = await httpResponse
  expect(response.status()).toBe(200)
  const body = await response.json() as RecommendationResponse
  expect(body.catalog_version).toBe(expected!.catalog_version)
  expect(body.ranking_version).toBe(expected!.ranking_version)
  expect(body.explanation_version).toBeTruthy()
  expect(body.status).toBe(expected!.status)
  expect(body.counts).toEqual(expected!.counts)
  expect(body.cards.map(card => card.id)).toEqual(expected!.profiles.map(profile => profile.id))
  expect(body.eligible_ids).toEqual(expected!.eligible_ids)
  const outgoing = response.request().postDataJSON() as RecommendationRequest
  expect(outgoing).toEqual({ ...query, duration_hours: query.duration_hours ?? null, language: query.language ?? null })
  await page.waitForFunction(() => window.__stage7Probe.current?.rendered_at_ms != null)
  const measured = await page.evaluate(() => window.__stage7Probe.current!)
  expect(measured.response).toEqual(body)
  const submitted = measured.submitted_at_ms!
  const fetched = measured.fetch_started_at_ms!
  const json = measured.json_ready_at_ms!
  const rendered = measured.rendered_at_ms!
  expect(rendered - submitted, 'Подбор с отображением укладывается в ориентир 10 секунд').toBeLessThan(10_000)
  expect(fetched).toBeGreaterThanOrEqual(submitted)
  expect(json).toBeGreaterThanOrEqual(fetched)
  expect(rendered).toBeGreaterThanOrEqual(json)
  await expect(page.locator('.contractor-card')).toHaveCount(expected!.counts.shown)
  for (const card of body.cards) {
   const shown = page.locator(`[data-profile-id="${card.id}"]`)
   await expect(shown).toContainText(card.explanation)
   await expect(shown).toContainText(card.price_label)
   for (const label of card.labels) await expect(shown).toContainText(label)
  }
  if (scenario === 'corporate-host-next-date') {
   await expect(page.locator('.date-comparison')).toContainText('Кики')
   await expect(page.locator('.date-comparison')).toContainText('занят на новую дату')
  }
  if (scenario === 'venue-busy') {
   await expect(page.locator('.date-comparison')).toContainText('Веджита')
   await expect(page.locator('.date-comparison')).toContainText('занят на новую дату')
  }
  if (scenario === 'rare-category') {
   for (const card of body.cards) {
    expect(card.max_hours).toBeNull()
    await expect(page.locator(`[data-profile-id="${card.id}"]`)).toContainText(card.duration_text)
   }
  }
  if (scenario === 'venue-free') {
   expect(body.cards[0].synthetic).toBe(true)
   expect(body.cards[0].price_imputed).toBe(true)
  }
  if (kind === 'scenario') {
   if (body.cards.length) await page.locator('.contractor-card').first().locator('summary').click()
   await page.screenshot({ path: fileURLToPath(new URL(`screenshots/${artifactPrefix}-${scenario}.png`, docs)), fullPage: true })
  }
  if (scenario === 'corporate-host') {
   if (original) expect(body).toEqual(original)
   else original = body
  }
  const { response: _response, render_pending: _pending, ...raw } = measured
  samples.push({
   scenario, kind, query, normalized_query: body.query, status: body.status,
   ids: body.cards.map(card => card.id), counts: body.counts,
   catalog_version: body.catalog_version, ranking_version: body.ranking_version,
   explanation_version: body.explanation_version,
   timing: { submit_to_render_ms: rendered - submitted, fetch_to_json_ms: json - fetched, json_to_render_ms: rendered - json, raw },
  })
 }

 for (const scenario of scenarios) await runScenario(scenario, 'scenario')
 for (let repetition = 1; repetition <= 5; repetition++) await runScenario('corporate-host', 'warm-repeat', repetition)
 expect(pageErrors).toEqual([])
 const warmed = samples.filter(sample => sample.kind === 'warm-repeat')
 const report = {
  scope: `${artifactPrefix}: production frontend → HTTP API → исходный CSV, 7 сценариев и 5 повторов основного запроса`,
  generated_at: new Date().toISOString(),
  environment: {
   frontend_mode: 'vite preview (production build)', base_url: baseURL,
   browser: browserName, browser_version: browser.version(), user_agent: userAgent,
   os: { platform: platform(), release: release(), architecture: arch(), cpu: cpus()[0]?.model ?? 'unknown' },
   node_version: process.version, viewport: page.viewportSize(),
   page_settings: await page.evaluate(() => ({ locale: navigator.language, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() })),
   workers: 1,
   network: 'Локальный браузер → Vite preview proxy → локальный Uvicorn; без искусственных задержек и внешних API.',
  },
  timing_method: {
   clock: 'performance.now() внутри одной браузерной страницы',
   performance_time_origin_ms: performanceTimeOrigin,
   submit_to_render: 'От capture-события submit до появления ожидаемых карточек/пустого состояния в DOM, двух requestAnimationFrame и синхронного чтения layout. Не включает ожидания и заполнение формы через Playwright.',
   fetch_to_json: 'От вызова fetch приложением до завершения response.json(), включая локальный proxy, сеть, backend и JSON; это не чистое серверное время.',
   instrumentation: 'Обёртка fetch/response.json и MutationObserver добавляют небольшой накладной расход. Замер DOM+layout после двух кадров служит приближением отображения, не подтверждает момент вывода пикселей композитором ОС.',
   warm_definition: 'Пять одинаковых запросов после всех семи демонстрационных сценариев в той же странице и серверном процессе. Статистика только этих пяти повторов.',
   excluded_work: 'Каталог и шрифты уже загружены. Автоподбор после изменения фильтров завершается до начала ручного замера. Запуск сервера, загрузка страницы/метаданных, заполнение формы, автоматические запросы, Playwright-ожидания и снимки экрана не входят в интервал submit→render.',
   percentile_method: 'nearest rank: отсортированное значение ceil(p × n); при n=5 p95 совпадает с максимумом.',
   limitations: 'Малая локальная выборка без нагрузки, сетевого throttling и мобильного устройства. Не SLA, не характеристика публичного сервера. Первый основной запрос тоже нельзя называть холодным: сервер мог уже обслужить другие проверки.',
  },
  source_baseline: 'docs/matching-report.json; версии каталога и ранжирования, статус, количества, все eligible_ids и показанные ID проверены для каждого сценария.',
  repeated_response_equal: true,
  first_page_request: samples[0],
  browser_errors: pageErrors,
  warm_summary: {
   submit_to_render: statistics(warmed.map(sample => sample.timing.submit_to_render_ms)),
   fetch_to_json: statistics(warmed.map(sample => sample.timing.fetch_to_json_ms)),
  },
  samples,
 }
 writeFileSync(new URL(`${artifactPrefix}-browser-report.json`, docs), JSON.stringify(report, null, 2) + '\n')
})
