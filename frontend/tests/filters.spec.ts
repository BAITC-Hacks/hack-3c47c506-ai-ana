import { test, expect, type Locator, type Page } from '@playwright/test'
import { createHash } from 'node:crypto'
import { readFileSync } from 'node:fs'
import type { RecommendationRequest, RecommendationResponse } from '../src/lib/api/generated'

type CatalogProfile = {
 id: string
 city: string
 categories: string[]
 event_formats: string[]
 busy_dates: string[]
 price_from_kzt: number
 max_hours: number | null
 languages: string[]
}

// This exported catalogue is checked against its original CSV, independently of
// the live response. The expected IDs below are fixed regression examples.
const catalogText = readFileSync(new URL('../../data/derived/catalog.jsonl', import.meta.url), 'utf8')
const catalog = new Map((catalogText.trim().split('\n').map(line => JSON.parse(line)) as CatalogProfile[]).map(profile => [profile.id, profile]))
const provenance = JSON.parse(readFileSync(new URL('../../data/derived/catalog.jsonl.meta.json', import.meta.url), 'utf8')) as {
 export_sha256: string
 records: { source_sha256: string }[]
}
const sourceHash = createHash('sha256').update(readFileSync(new URL('../../hackathon dataset anonymized .csv', import.meta.url))).digest('hex')
const initialQuery: RecommendationRequest = {
 city: 'Алматы', category: 'Ведущий', event_date: '2026-09-30', event_format: 'корпоратив',
 budget_kzt: 1_000_000, duration_hours: null, language: null,
}
const initialIds = ['HK-88430', 'HK-44923', 'HK-35215', 'HK-27222', 'HK-44733', 'HK-77838']
const submit = (page: Page) => page.getByRole('button', { name: /^(Подобрать подрядчиков|Обновить подбор)$/ })
const cards = (page: Page) => page.locator('.contractor-card')
const normalized = (query: RecommendationRequest | RecommendationResponse['query']) => ({
 city: query.city, category: query.category, event_date: query.event_date, event_format: query.event_format,
 budget_kzt: query.budget_kzt, duration_hours: query.duration_hours == null ? null : Number(query.duration_hours), language: query.language || null,
})

async function queryAfter(page: Page, query: RecommendationRequest, action: () => Promise<unknown>) {
 const responsePromise = page.waitForResponse(response => response.url().endsWith('/api/recommendations')
  && response.request().method() === 'POST'
  && JSON.stringify(normalized(response.request().postDataJSON() as RecommendationRequest)) === JSON.stringify(normalized(query)))
 await action()
 const response = await responsePromise
 expect(response.status()).toBe(200)
 expect(response.request().postDataJSON()).toEqual(query)
 const body = await response.json() as RecommendationResponse
 expect(normalized(body.query)).toEqual(normalized(query))
 return body
}

async function assertResults(page: Page, body: RecommendationResponse, expectedIds: string[], status: RecommendationResponse['status'] = 'MATCHED') {
 expect(body.status).toBe(status)
 expect(body.eligible_ids).toEqual(expectedIds)
 expect(body.cards.map(card => card.id)).toEqual(expectedIds.slice(0, 3))
 await expect(cards(page)).toHaveCount(Math.min(expectedIds.length, 3))
 await expect.poll(() => cards(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id')))).toEqual(expectedIds.slice(0, 3))
 const query = body.query
 for (const card of body.cards) {
  const source = catalog.get(card.id)!
  expect(source, `Каталожный профиль ${card.id}`).toBeDefined()
  expect(source.city).toBe(query.city)
  expect(source.categories).toContain(query.category)
  expect(source.event_formats).toContain(query.event_format)
  expect(source.busy_dates).not.toContain(query.event_date)
  expect(source.price_from_kzt).toBeLessThanOrEqual(query.budget_kzt)
  if (query.language) expect(source.languages).toContain(query.language)
  if (query.duration_hours && source.max_hours !== null) expect(source.max_hours).toBeGreaterThanOrEqual(Number(query.duration_hours))
  await expect(page.locator(`[data-profile-id="${card.id}"]`)).toContainText(card.anon_name)
 }
 await expect(page.locator('.example-context')).toContainText(query.city)
 await expect(page.locator('.example-context')).toContainText(query.category)
 if (status !== 'MATCHED') await expect(page.locator(`.result-state[data-status="${status}"]`)).toBeVisible()
}

async function edit(control: Locator, value: string, kind: 'select' | 'input') {
 if (kind === 'select') await control.selectOption(value)
 else await control.fill(value)
}

test.beforeAll(async ({ request }) => {
 expect(createHash('sha256').update(catalogText).digest('hex')).toBe(provenance.export_sha256)
 expect(new Set(provenance.records.map(record => record.source_sha256))).toEqual(new Set([sourceHash]))
 const metadata = await request.get('/api/catalog/meta')
 expect(metadata.ok()).toBeTruthy()
 expect((await metadata.json()).source_sha256).toBe(sourceHash)
})

test.beforeEach(async ({ page }) => {
 await page.goto('/')
 await expect(submit(page)).toBeEnabled()
})

const singleFilters: {
 label: string
 key: keyof RecommendationRequest
 value: string | number
 kind: 'select' | 'input'
 ids: string[]
}[] = [
 { label: 'Город', key: 'city', value: 'Астана', kind: 'select', ids: ['HK-37181', 'HK-80581'] },
 { label: 'Кого ищем', key: 'category', value: 'Фотограф', kind: 'select', ids: ['HK-20640', 'HK-30583', 'HK-16628'] },
 { label: 'Дата события', key: 'event_date', value: '2026-10-01', kind: 'input', ids: ['HK-88430', 'HK-44923'] },
 { label: 'Формат', key: 'event_format', value: 'свадьба', kind: 'select', ids: ['HK-44923', 'HK-35215', 'HK-42352', 'HK-27222', 'HK-77838'] },
 { label: 'Бюджет, ₸', key: 'budget_kzt', value: 650000, kind: 'input', ids: ['HK-88430', 'HK-44923'] },
 { label: 'Длительность, ч', key: 'duration_hours', value: 8, kind: 'input', ids: ['HK-44923', 'HK-35215', 'HK-27222', 'HK-77838'] },
 { label: 'Язык', key: 'language', value: 'английский', kind: 'select', ids: ['HK-35215', 'HK-44733'] },
]

for (const filter of singleFilters) {
 test(`фильтр «${filter.label}» автоматически обновляет реальную выдачу`, async ({ page }) => {
  await assertResults(page, await queryAfter(page, initialQuery, () => submit(page).click()), initialIds)
  const query = { ...initialQuery, [filter.key]: filter.value }
  const body = await queryAfter(page, query, () => edit(page.getByLabel(filter.label, { exact: true }), String(filter.value), filter.kind))
  await assertResults(page, body, filter.ids)
  expect(body.eligible_ids).not.toEqual(initialIds)
  await expect(page.getByLabel(filter.label, { exact: true })).toHaveValue(String(filter.value))
  if (filter.key === 'event_date') {
   await expect(page.locator('.date-comparison')).toContainText('Кики')
   await expect(page.locator('.date-comparison')).toContainText('занят на новую дату')
   await assertResults(page, await queryAfter(page, query, () => submit(page).click()), filter.ids)
   await expect(page.locator('.date-comparison')).toContainText('Кики')
   await expect(page.locator('.date-comparison')).toContainText('занят на новую дату')
  }
 })
}

test('бюджет, дробная длительность и язык работают вместе, необязательные ограничения можно снять', async ({ page }) => {
 let query: RecommendationRequest = { ...initialQuery, budget_kzt: 499999 }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Бюджет, ₸', { exact: true }).fill('499999')), [], 'NO_MATCHES')
 query = { ...query, budget_kzt: 500000 }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Бюджет, ₸', { exact: true }).fill('500000')), ['HK-88430'])
 query = { ...query, duration_hours: 6 }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Длительность, ч', { exact: true }).fill('6')), ['HK-88430'])
 query = { ...query, duration_hours: 6.25 }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Длительность, ч', { exact: true }).fill('6.25')), [], 'NO_MATCHES')
 query = { ...query, duration_hours: null }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Длительность, ч', { exact: true }).fill('')), ['HK-88430'])
 query = { ...query, language: 'английский' }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Язык', { exact: true }).selectOption('английский')), [], 'NO_MATCHES')
 query = { ...query, language: null }
 await assertResults(page, await queryAfter(page, query, () => page.getByLabel('Язык', { exact: true }).selectOption('')), ['HK-88430'])
})

const examples: { label: string; query: RecommendationRequest; ids: string[]; status: RecommendationResponse['status'] }[] = [
 { label: 'Ведущие в Алматы', query: initialQuery, ids: initialIds, status: 'MATCHED' },
 { label: 'Редкая категория', query: { ...initialQuery, category: 'Декоратор', event_date: '2026-09-23', budget_kzt: 2500000, duration_hours: 5 }, ids: ['HK-11484', 'HK-90004'], status: 'MATCHED' },
 { label: 'Небольшой бюджет', query: { ...initialQuery, budget_kzt: 100000 }, ids: [], status: 'NO_MATCHES' },
 { label: 'Декораторы в Астане', query: { ...initialQuery, city: 'Астана', category: 'Декоратор', event_date: '2026-09-23', budget_kzt: 2500000 }, ids: [], status: 'CATEGORY_UNAVAILABLE' },
]

for (const example of examples) {
 test(`пример «${example.label}» заменяет фильтры и выполняет один запрос`, async ({ page }) => {
  let requests = 0
  page.on('request', request => { if (request.url().endsWith('/api/recommendations')) requests++ })
  const body = await queryAfter(page, example.query, () => page.getByRole('button', { name: example.label, exact: true }).click())
  await assertResults(page, body, example.ids, example.status)
  for (const field of singleFilters) {
   await expect(page.getByLabel(field.label, { exact: true })).toHaveValue(String(example.query[field.key] ?? ''))
  }
  // Wait through the automatic-filter debounce: examples must not search twice.
  await page.waitForTimeout(650)
  expect(requests).toBe(1)
 })
}

test('сброс фильтров отменяет устаревший запрос и сразу возвращает исходный подбор', async ({ page, request }) => {
 const changedQuery = { ...initialQuery, city: 'Астана' }
 const oldResponse = await request.post('/api/recommendations', { data: changedQuery })
 expect(oldResponse.ok()).toBeTruthy()
 const oldBody = await oldResponse.json()
 let release: (() => Promise<void>) | undefined
 let intercepted!: () => void
 const pending = new Promise<void>(resolve => { intercepted = resolve })
 await page.route('**/api/recommendations', async route => {
  if (route.request().postDataJSON().city === 'Астана') {
   release = () => route.fulfill({ json: oldBody })
   intercepted()
  } else await route.continue()
 })
 await page.getByLabel('Город', { exact: true }).selectOption('Астана')
 await pending
 await expect(page.locator('.result-state[data-status="loading"]')).toBeVisible()
 const reset = await queryAfter(page, initialQuery, () => page.getByRole('button', { name: 'Сбросить фильтры', exact: true }).click())
 await assertResults(page, reset, initialIds)
 await release?.().catch(error => { if (!/closed|aborted|invalid interception/i.test(String(error))) throw error })
 await page.waitForTimeout(650)
 await expect(page.getByLabel('Город', { exact: true })).toHaveValue('Алматы')
 await expect.poll(() => cards(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id')))).toEqual(initialIds.slice(0, 3))
})

test('кнопка повторного подбора восстанавливает выбранные фильтры после сетевой ошибки', async ({ page }) => {
 const query = { ...initialQuery, language: 'английский' }
 await page.route('**/api/recommendations', route => route.abort('failed'), { times: 1 })
 await page.getByLabel('Язык', { exact: true }).selectOption('английский')
 await expect(page.locator('.result-state[data-status="error"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 const body = await queryAfter(page, query, () => page.getByRole('button', { name: 'Повторить подбор', exact: true }).click())
 await assertResults(page, body, ['HK-35215', 'HK-44733'])
 await expect(page.getByLabel('Язык', { exact: true })).toHaveValue('английский')
})

test('кнопка подбора применяет отредактированные фильтры без второго автоматического запроса', async ({ page }) => {
 await page.clock.install({ time: new Date('2026-09-23T12:00:00Z') })
 await page.clock.pauseAt(new Date('2026-09-23T13:00:00Z'))
 let requests = 0
 page.on('request', request => { if (request.url().endsWith('/api/recommendations')) requests++ })
 const query = { ...initialQuery, budget_kzt: 650000 }
 const body = await queryAfter(page, query, async () => {
  await page.getByLabel('Бюджет, ₸', { exact: true }).fill('650000')
  await submit(page).click()
 })
 await assertResults(page, body, ['HK-88430', 'HK-44923'])
 await page.clock.runFor(650)
 expect(requests).toBe(1)
})

test('неверная длительность показывает ошибку без запроса, исправление автоматически возвращает результат', async ({ page }) => {
 let requests = 0
 page.on('request', request => { if (request.url().endsWith('/api/recommendations')) requests++ })
 await assertResults(page, await queryAfter(page, initialQuery, () => submit(page).click()), initialIds)
 await page.getByLabel('Длительность, ч', { exact: true }).fill('0')
 await expect(page.getByLabel('Длительность, ч', { exact: true })).toHaveAttribute('aria-invalid', 'true')
 await expect(page.locator('.result-state[data-status="validation"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 expect(requests).toBe(1)
 const query = { ...initialQuery, duration_hours: 8 }
 const body = await queryAfter(page, query, () => page.getByLabel('Длительность, ч', { exact: true }).fill('8'))
 await assertResults(page, body, ['HK-44923', 'HK-35215', 'HK-27222', 'HK-77838'])
 await expect(page.getByLabel('Длительность, ч', { exact: true })).toHaveAttribute('aria-invalid', 'false')
 expect(requests).toBe(2)
})
