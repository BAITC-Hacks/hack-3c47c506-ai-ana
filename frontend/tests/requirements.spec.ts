import { test, expect, type Page } from '@playwright/test'
import { mkdirSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import type { RecommendationRequest, RecommendationResponse } from '../src/lib/api/generated'
import { artifactPrefix } from './artifacts'

type SourceProfile = {
 id: string
 anon_name: string
 description: string
 busy_dates: string[]
}

const catalog = readFileSync(new URL('../../data/derived/catalog.jsonl', import.meta.url), 'utf8')
 .trim().split('\n').map(line => JSON.parse(line) as SourceProfile)
const query: RecommendationRequest = {
 city: 'Алматы', category: 'Национальный ансамбль', event_format: 'свадьба',
 event_date: '2026-09-24', budget_kzt: 500_000, language: null, duration_hours: null,
}
const expectedIds = ['HK-19103', 'HK-39301', 'HK-92824']
const submit = (page: Page) => page.getByRole('button', { name: /^(Подобрать подрядчиков|Обновить подбор)$/ })

function withoutIdentity(text: string) {
 let stripped = text.toLocaleLowerCase('ru-RU')
 const identities = catalog.flatMap(profile => [profile.id, profile.anon_name])
  .sort((left, right) => right.length - left.length)
 for (const identity of identities) stripped = stripped.replaceAll(identity.toLocaleLowerCase('ru-RU'), '')
 return stripped.replace(/[^\p{L}\p{N}]+/gu, ' ').trim()
}

async function responseAfter(page: Page, action: () => Promise<unknown>) {
 // Filtering on all request fields avoids capturing intermediate automatic
 // requests while the user is changing city/category/date/format/budget.
 const responsePromise = page.waitForResponse(response => {
  if (!response.url().endsWith('/api/recommendations') || response.request().method() !== 'POST') return false
  const sent = response.request().postDataJSON() as RecommendationRequest
  return Object.entries(query).every(([key, value]) => sent[key as keyof RecommendationRequest] === value)
 })
 await action()
 const response = await responsePromise
 expect(response.status()).toBe(200)
 return await response.json() as RecommendationResponse
}

test('ансамбли с одинаковой ценой имеют разные объяснения из источника и стабильный повтор', async ({ page }) => {
 const errors: string[] = []
 page.on('pageerror', error => errors.push(error.message))
 await page.goto('/')
 await expect(submit(page)).toBeEnabled()
 await page.getByLabel('Кого ищем', { exact: true }).selectOption(query.category)
 await page.getByLabel('Формат', { exact: true }).selectOption(query.event_format)
 await page.getByLabel('Дата события', { exact: true }).fill(query.event_date)
 const body = await responseAfter(page, () => page.getByLabel('Бюджет, ₸', { exact: true }).fill(String(query.budget_kzt)))
 expect(body.status).toBe('MATCHED')
 expect(body.cards.map(card => card.id)).toEqual(expectedIds)
 expect(body.cards[1].price_from_kzt).toBe(500_000)
 expect(body.cards[2].price_from_kzt).toBe(500_000)
 expect(new Set(body.cards.map(card => withoutIdentity(card.explanation))).size).toBe(3)
 const quotes = body.cards.map(card => card.evidence.find(item => item.code === 'DESCRIPTION_FEATURE')?.quote)
 expect(quotes.every(Boolean)).toBe(true)
 expect(new Set(quotes.map(quote => withoutIdentity(quote!))).size).toBe(3)

 await expect.poll(() => page.locator('.contractor-card').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id'))))
  .toEqual(expectedIds)
 for (const card of body.cards) {
  const source = catalog.find(profile => profile.id === card.id)!
  const quote = card.evidence.find(item => item.code === 'DESCRIPTION_FEATURE')!.quote!
  expect(source.description).toContain(quote)
  expect(source.busy_dates).not.toContain(query.event_date)
  expect(card.warnings.some(warning => warning.code === 'SHARED_EXPLANATION')).toBe(false)
  await expect(page.locator(`[data-profile-id="${card.id}"] .explanation p`)).toHaveText(card.explanation)
 }
 const displayed = await page.locator('.contractor-card .explanation p').allTextContents()
 expect(new Set(displayed.map(withoutIdentity)).size).toBe(3)

 const repeated = await responseAfter(page, () => submit(page).click())
 expect(repeated).toEqual(body)
 await expect(page.locator('.results [aria-live="polite"]')).toHaveAttribute('aria-busy', 'false')
 await expect.poll(() => page.locator('.contractor-card').evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id'))))
  .toEqual(expectedIds)
 await page.locator('.contractor-card').first().locator('summary').click()
 const screenshots = new URL('../../docs/screenshots/', import.meta.url)
 mkdirSync(screenshots, { recursive: true })
 await page.screenshot({ path: fileURLToPath(new URL(`${artifactPrefix}-national-ensemble.png`, screenshots)), fullPage: true })
 expect(errors).toEqual([])
})
