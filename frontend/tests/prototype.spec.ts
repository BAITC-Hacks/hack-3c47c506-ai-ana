import { test, expect, type Page } from '@playwright/test'
import type { RecommendationRequest, RecommendationResponse } from '../src/lib/api/generated'

const mainQuery: RecommendationRequest = {
 city: 'Алматы', category: 'Ведущий', event_format: 'корпоратив',
 event_date: '2026-09-30', budget_kzt: 1_000_000,
 duration_hours: null, language: null,
}
const cards = (page: Page) => page.locator('.contractor-card')
const submit = (page: Page) => page.getByRole('button', { name: /^(Подобрать подрядчиков|Обновить подбор)$/ })

async function openApplication(page: Page) {
 await page.goto('/')
 await expect(submit(page)).toBeEnabled()
 await expect(page.getByLabel('Город', { exact: true })).toHaveValue('Алматы')
 await expect(cards(page)).toHaveCount(0)
}

async function search(page: Page) {
 const response = page.waitForResponse(r => r.url().endsWith('/api/recommendations') && r.request().method() === 'POST')
 await submit(page).click()
 const result = await response
 expect(result.ok()).toBeTruthy()
 return await result.json() as RecommendationResponse
}

test('реальный подбор, основания и смена даты сохраняют параметры события', async ({ page }) => {
 await openApplication(page)
 await expect(page.locator('.result-state[data-status="initial"]')).toBeVisible()
 const first = await search(page)
 expect(first.status).toBe('MATCHED')
 await expect(cards(page)).toHaveCount(3)
 expect(await cards(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id'))))
  .toEqual(['HK-88430', 'HK-44923', 'HK-35215'])
 await cards(page).first().locator('summary').click()
 await expect(cards(page).first().locator('details')).toHaveAttribute('open', '')
 await expect(cards(page).first()).toContainText(first.cards[0].evidence[0].text)
 await expect(cards(page).first()).toContainText(first.cards[0].explanation)
 await page.getByLabel('Дата события', { exact: true }).fill('2026-10-01')
 const updated = await search(page)
 expect(updated.status).toBe('MATCHED')
 await expect(cards(page)).toHaveCount(2)
 await expect(page.locator('[data-profile-id="HK-35215"]')).toHaveCount(0)
 await expect(page.locator('.date-comparison')).toContainText('Кики')
 await expect(page.locator('.date-comparison')).toContainText(/занят/i)
 for (const [label, value] of [['Город', 'Алматы'], ['Кого ищем', 'Ведущий'], ['Формат', 'корпоратив'], ['Бюджет, ₸', '1000000'], ['Длительность, ч', ''], ['Язык', '']]) {
  await expect(page.getByLabel(label, { exact: true })).toHaveValue(value)
 }
 await expect(page.locator('.example-context')).toContainText(/01\.10\.2026|2026-10-01/)
})

test('отсутствие подходящих и отсутствие категории имеют разные состояния', async ({ page }) => {
 await openApplication(page)
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('100000')
 expect((await search(page)).status).toBe('NO_MATCHES')
 await expect(page.locator('.result-state[data-status="NO_MATCHES"]')).toBeVisible()
 await expect(page.getByRole('heading', { name: 'По этим условиям нет подходящих' })).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 await page.getByLabel('Город', { exact: true }).selectOption('Астана')
 // Категории доступны из всего каталога, включая отсутствующие в выбранном городе.
 await page.getByLabel('Кого ищем', { exact: true }).selectOption('Декоратор')
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('2500000')
 expect((await search(page)).status).toBe('CATEGORY_UNAVAILABLE')
 await expect(page.locator('.result-state[data-status="CATEGORY_UNAVAILABLE"]')).toBeVisible()
 await expect(page.getByRole('heading', { name: 'В этом городе пока нет категории' })).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
})

test('одна и две карточки показывают происхождение сведений и неизвестную длительность', async ({ page }) => {
 await openApplication(page)
 await page.getByLabel('Город', { exact: true }).selectOption('Астана')
 await page.getByLabel('Кого ищем', { exact: true }).selectOption('Отель')
 await page.getByLabel('Дата события', { exact: true }).fill('2026-09-23')
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('3000000')
 await page.getByLabel('Длительность, ч', { exact: true }).fill('5')
 const hotel = await search(page)
 await expect(cards(page)).toHaveCount(1)
 await expect(cards(page)).toHaveAttribute('data-profile-id', 'HK-90012')
 for (const label of hotel.cards[0].labels) await expect(cards(page)).toContainText(label)
 await expect(cards(page)).toContainText(hotel.cards[0].price_label)
 await page.getByLabel('Город', { exact: true }).selectOption('Алматы')
 await page.getByLabel('Кого ищем', { exact: true }).selectOption('Декоратор')
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('2500000')
 const decorators = await search(page)
 await expect(cards(page)).toHaveCount(2)
 for (const card of decorators.cards) {
  expect(card.max_hours).toBeNull()
  await expect(page.locator(`[data-profile-id="${card.id}"]`)).toContainText(card.duration_text)
 }
})

test('валидация в браузере и HTTP 422 не превращаются в пустой результат', async ({ page }) => {
 let requests = 0
 page.on('request', request => { if (request.url().endsWith('/api/recommendations')) requests++ })
 await openApplication(page)
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('-1')
 await submit(page).click()
 await expect(page.getByLabel('Бюджет, ₸', { exact: true })).toHaveAttribute('aria-invalid', 'true')
 await expect(cards(page)).toHaveCount(0)
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('1000000')
 await page.getByLabel('Дата события', { exact: true }).fill('2027-01-01')
 await submit(page).click()
 await expect(page.getByLabel('Дата события', { exact: true })).toHaveAttribute('aria-invalid', 'true')
 expect(requests).toBe(0)
 await page.getByLabel('Дата события', { exact: true }).fill('2026-09-30')
 await page.route('**/api/recommendations', route => route.fulfill({
  status: 422, json: { code: 'INVALID_QUERY', message: 'Проверьте параметры мероприятия.', issues: [{ field: 'budget_kzt', message: 'Тест: уточните бюджет.' }] },
 }), { times: 1 })
 await submit(page).click()
 await expect(page.getByText('Тест: уточните бюджет.', { exact: true })).toBeVisible()
 await expect(page.getByLabel('Бюджет, ₸', { exact: true })).toHaveAttribute('aria-invalid', 'true')
 await expect(page.locator('.result-state[data-status="validation"]')).toBeVisible()
 await search(page)
 await expect(cards(page)).toHaveCount(3)
})

test('техническая ошибка и недоступный каталог позволяют повторить запрос', async ({ page }) => {
 await openApplication(page)
 await page.route('**/api/recommendations', route => route.fulfill({
  status: 503, json: { code: 'CATALOG_LOAD_FAILED', message: 'Каталог недоступен.', issues: [] },
 }), { times: 1 })
 await submit(page).click()
 await expect(page.locator('.result-state[data-status="error"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 await search(page)
 await expect(cards(page)).toHaveCount(3)
 await page.route('**/api/recommendations', route => route.fulfill({
  status: 200, json: { status: 'MATCHED' },
 }), { times: 1 })
 await submit(page).click()
 await expect(page.locator('.result-state[data-status="error"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 await search(page)
 await expect(cards(page)).toHaveCount(3)
 let metadataUnavailable = true
 await page.route('**/api/catalog/meta', route => metadataUnavailable
  ? route.fulfill({ status: 503, json: { code: 'CATALOG_LOAD_FAILED', message: 'Каталог недоступен.', issues: [] } })
  : route.continue())
 await page.reload()
 await expect(page.locator('.catalog-error')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 metadataUnavailable = false
 await page.getByRole('button', { name: 'Повторить загрузку', exact: true }).click()
 await expect(submit(page)).toBeEnabled()
 await search(page)
 await expect(cards(page)).toHaveCount(3)
})

test('новый запрос очищает карточки, запоздалый ответ не заменяет последний', async ({ page, request }) => {
 const delayedResponse = await request.post('/api/recommendations', { data: { ...mainQuery, event_date: '2026-10-01' } })
 const emptyResponse = await request.post('/api/recommendations', { data: { ...mainQuery, budget_kzt: 100000 } })
 expect(delayedResponse.ok()).toBeTruthy()
 expect(emptyResponse.ok()).toBeTruthy()
 const delayed = await delayedResponse.json()
 const empty = await emptyResponse.json()
 await openApplication(page)
 await search(page)
 await expect(cards(page)).toHaveCount(3)
 let requestNumber = 0
 let releaseFirst: (() => Promise<void>) | undefined
 let intercepted: () => void = () => {}
 const firstIntercepted = new Promise<void>(resolve => { intercepted = resolve })
 await page.route('**/api/recommendations', async route => {
  if (++requestNumber === 1) {
   releaseFirst = () => route.fulfill({ json: delayed })
   intercepted()
   return
  }
  await route.fulfill({ json: empty })
 })
 await page.getByLabel('Дата события', { exact: true }).fill('2026-10-01')
 await submit(page).click()
 await firstIntercepted
 await expect(page.locator('.result-state[data-status="loading"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 await page.getByLabel('Дата события', { exact: true }).fill('2026-09-30')
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('100000')
 await submit(page).click()
 await expect(page.locator('.result-state[data-status="NO_MATCHES"]')).toBeVisible()
 // Старый запрос может быть уже отменён AbortController — это тоже корректная защита.
 await releaseFirst?.().catch(error => { if (!/closed|aborted|invalid interception/i.test(String(error))) throw error })
 await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))))
 await expect(page.locator('.result-state[data-status="NO_MATCHES"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 await expect(page.getByLabel('Бюджет, ₸', { exact: true })).toHaveValue('100000')
})

test('цвет сохраняется без нового подбора и потери формы или раскрытых оснований', async ({ page }) => {
 let requests = 0
 page.on('request', request => { if (request.url().endsWith('/api/recommendations')) requests++ })
 await openApplication(page)
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('1100000')
 await search(page)
 await expect(cards(page)).toHaveCount(3)
 const ids = await cards(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id')))
 await cards(page).first().locator('summary').click()
 await page.getByRole('button', { name: 'Оформление', exact: true }).click()
 for (const name of ['Зелёный', 'Фиолетовый', 'Оранжевый', 'Синий']) {
  await page.getByRole('button', { name, exact: true }).click()
  await expect(page.getByRole('button', { name, exact: true })).toHaveAttribute('aria-pressed', 'true')
 }
 for (const [background, foreground] of [['#FFFFFF', '#000000'], ['#000000', '#FFFFFF']]) {
  await page.getByLabel('Свой цвет', { exact: true }).fill(background)
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--on-accent').trim())).toBe(foreground)
 }
 await page.getByLabel('Свой цвет', { exact: true }).fill('oops')
 await expect(page.getByText('Введите цвет в формате #RRGGBB.')).toBeVisible()
 await expect(page.getByLabel('Бюджет, ₸', { exact: true })).toHaveValue('1100000')
 await expect(cards(page).first().locator('details')).toHaveAttribute('open', '')
 expect(await cards(page).evaluateAll(nodes => nodes.map(node => node.getAttribute('data-profile-id')))).toEqual(ids)
 expect(requests).toBe(1)
 await page.reload()
 await page.getByRole('button', { name: 'Оформление', exact: true }).click()
 await expect(page.getByLabel('Свой цвет', { exact: true })).toHaveValue('#000000')
 await page.getByRole('button', { name: 'Вернуть стандартный цвет' }).click()
 await expect(page.getByLabel('Свой цвет', { exact: true })).toHaveValue('#2563EB')
})

test('повреждённое и недоступное хранилище не мешают оформлению и реальному подбору', async ({ browser }) => {
 for (const mode of ['corrupt', 'unavailable'] as const) {
  const context = await browser.newContext({ baseURL: 'http://127.0.0.1:5174' })
  await context.addInitScript(storageMode => {
   if (storageMode === 'corrupt') window.localStorage.setItem('ai-ana-accent', 'not-a-color')
   else Object.defineProperty(window, 'localStorage', { get() { throw new Error('Storage unavailable') } })
  }, mode)
  const page = await context.newPage()
  await openApplication(page)
  await page.getByRole('button', { name: 'Оформление', exact: true }).click()
  await expect(page.getByLabel('Свой цвет', { exact: true })).toHaveValue('#2563EB')
  await page.getByRole('button', { name: 'Зелёный', exact: true }).click()
  await expect(page.getByLabel('Свой цвет', { exact: true })).toHaveValue('#15803D')
  await page.getByRole('button', { name: 'Закрыть настройки', exact: true }).click()
  await search(page)
  await expect(cards(page)).toHaveCount(3)
  await context.close()
 }
})

test('реальные карточки и логотип помещаются на ширинах 1440, 768, 390 и 320', async ({ page }) => {
 const errors: string[] = []
 page.on('pageerror', error => errors.push(error.message))
 await openApplication(page)
 await search(page)
 await expect(cards(page)).toHaveCount(3)
 await cards(page).first().locator('summary').click()
 for (const width of [1440, 768, 390, 320]) {
  await page.setViewportSize({ width, height: 1000 })
  await page.evaluate(() => document.fonts.ready)
  await expect(page.getByRole('heading', { name: 'Ваше событие. Подходящие люди.' })).toBeVisible()
  await expect(page.getByRole('img', { name: 'Логотип AI-ANA' })).toBeVisible()
  expect(await page.getByRole('img', { name: 'Логотип AI-ANA' }).evaluate(img => (img as HTMLImageElement).naturalWidth)).toBeGreaterThan(0)
  const overflow = await page.evaluate(() => [...document.querySelectorAll('*')]
   .filter(element => element.getBoundingClientRect().right > innerWidth + 1)
   .map(element => ({ tag: element.tagName, cls: element.className, right: element.getBoundingClientRect().right })))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), JSON.stringify({ width, overflow })).toBeTruthy()
  await page.screenshot({ path: `../docs/screenshots/stage6-${width}.png`, fullPage: true })
 }
 expect(errors).toEqual([])
})
