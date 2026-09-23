import { test, expect, type Locator, type Page, type Route } from '@playwright/test'
import type { CatalogMetadata, RecommendationResponse } from '../src/lib/api/generated'
import { artifactPrefix } from './artifacts'

test.use({ reducedMotion: 'reduce' })

const cards = (page: Page) => page.locator('.contractor-card')
const submit = (page: Page) => page.getByRole('button', { name: /^(Подобрать подрядчиков|Обновить подбор)$/ })

async function openApplication(page: Page) {
 await page.goto('/')
 await expect(submit(page)).toBeEnabled()
}

async function search(page: Page) {
 const response = page.waitForResponse(result => result.url().endsWith('/api/recommendations') && result.request().method() === 'POST')
 await submit(page).click()
 const result = await response
 expect(result.ok()).toBeTruthy()
 return await result.json() as RecommendationResponse
}

// Measure the rendered foreground/background, including CSS color-mix in interaction states.
async function contrast(locator: Locator) {
 return locator.evaluate(element => {
  const style = getComputedStyle(element)
  const canvas = document.createElement('canvas')
  canvas.width = canvas.height = 1
  const context = canvas.getContext('2d')!
  const luminance = (color: string) => {
   context.clearRect(0, 0, 1, 1)
   context.fillStyle = color
   context.fillRect(0, 0, 1, 1)
   const pixel = context.getImageData(0, 0, 1, 1).data
   const linear = Array.from(pixel).slice(0, 3).map(channel => {
    const value = channel / 255
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
   })
   return linear[0] * 0.2126 + linear[1] * 0.7152 + linear[2] * 0.0722
  }
  const text = luminance(style.color)
  const background = luminance(style.backgroundColor)
  return (Math.max(text, background) + 0.05) / (Math.min(text, background) + 0.05)
 })
}

test('таймаут, потеря сети и HTTP 500 очищают выдачу и позволяют повторить подбор', async ({ page }) => {
 await page.setViewportSize({ width: 390, height: 1000 })
 await openApplication(page)
 await page.evaluate(() => document.fonts.ready)
 await page.screenshot({ path: `../docs/screenshots/${artifactPrefix}-initial-390.png`, fullPage: true })
 await search(page)
 await expect(cards(page)).toHaveCount(3)
 await page.clock.install()

 let stalledRoute: Route | undefined
 let markIntercepted: () => void = () => {}
 const intercepted = new Promise<void>(resolve => { markIntercepted = resolve })
 await page.route('**/api/recommendations', route => {
  stalledRoute = route
  markIntercepted()
 }, { times: 1 })
 await submit(page).click()
 await intercepted
 await expect(page.locator('.result-state[data-status="loading"]')).toBeVisible()
 await expect(cards(page)).toHaveCount(0)
 await page.screenshot({ path: `../docs/screenshots/${artifactPrefix}-loading-390.png`, fullPage: true })
 // Exercise the application's real abort deadline without spending twelve wall-clock seconds.
 await page.clock.runFor(12_001)
 await expect(page.locator('.result-state[data-status="error"]')).toContainText('Сервер долго не отвечает')
 await expect(cards(page)).toHaveCount(0)
 await page.screenshot({ path: `../docs/screenshots/${artifactPrefix}-timeout-390.png`, fullPage: true })
 // The browser has already cancelled this fetch; release any remaining intercepted route.
 await stalledRoute?.abort().catch(() => {})
 await search(page)
 await expect(cards(page)).toHaveCount(3)

 for (const failure of ['network', 'server'] as const) {
  await test.step(failure === 'network' ? 'Разрыв соединения' : 'Внутренняя ошибка сервера', async () => {
   await page.route('**/api/recommendations', route => failure === 'network'
    ? route.abort('internetdisconnected')
    : route.fulfill({ status: 500, json: { code: 'INTERNAL_ERROR', message: 'Сервис временно недоступен.', issues: [] } }), { times: 1 })
   await submit(page).click()
   await expect(page.locator('.result-state[data-status="error"]')).toContainText(failure === 'network'
    ? 'Не удалось связаться с сервером'
    : 'Сервис временно недоступен.')
   await expect(cards(page)).toHaveCount(0)
   await expect(page.getByLabel('Бюджет, ₸', { exact: true })).toHaveValue('1000000')
   await search(page)
   await expect(cards(page)).toHaveCount(3)
  })
 }
})

test('оформление доступно с клавиатуры, текст кнопки контрастен во всех состояниях', async ({ page }) => {
 await openApplication(page)
 const trigger = page.getByRole('button', { name: 'Оформление', exact: true })
 await trigger.focus()
 await page.keyboard.press('Enter')
 const close = page.getByRole('button', { name: 'Закрыть настройки', exact: true })
 await expect(close).toBeFocused()
 expect(await close.evaluate(element => {
  const style = getComputedStyle(element)
  return element.matches(':focus-visible') && style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) >= 2
 })).toBeTruthy()
 await page.keyboard.press('Tab')
 await expect(page.getByRole('button', { name: 'Синий', exact: true })).toBeFocused()
 await page.keyboard.press('Tab')
 await expect(page.getByRole('button', { name: 'Зелёный', exact: true })).toBeFocused()
 await page.keyboard.press('Space')
 await expect(page.getByRole('button', { name: 'Зелёный', exact: true })).toHaveAttribute('aria-pressed', 'true')
 await page.keyboard.press('Escape')
 await expect(trigger).toBeFocused()
 await expect(page.getByRole('region', { name: 'Настройки оформления' })).toHaveCount(0)

 // The two middle grays straddle the foreground-color switch; extremes and presets cover the rest.
 for (const accent of ['#2563EB', '#15803D', '#7C3AED', '#C2410C', '#757575', '#767676', '#000000', '#FFFFFF']) {
  await trigger.click()
  await page.getByLabel('Свой цвет', { exact: true }).fill(accent)
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim())).toBe(accent)
  await page.keyboard.press('Escape')
  await page.mouse.move(0, 0)
  expect(await contrast(submit(page)), `${accent}: обычное состояние`).toBeGreaterThanOrEqual(4.5)
  await submit(page).hover()
  expect(await contrast(submit(page)), `${accent}: наведение`).toBeGreaterThanOrEqual(4.5)
  await page.mouse.down()
  expect(await submit(page).evaluate(element => element.matches(':active'))).toBeTruthy()
  expect(await contrast(submit(page)), `${accent}: нажатие`).toBeGreaterThanOrEqual(4.5)
  await page.mouse.move(0, 0)
  await page.mouse.up()
 }
 await expect(cards(page)).toHaveCount(0)
})

test('смена даты объясняет появление карточек и выход подходящего профиля за первые три', async ({ page }) => {
 await openApplication(page)
 await page.getByLabel('Город', { exact: true }).selectOption('Астана')
 await page.getByLabel('Кого ищем', { exact: true }).selectOption('Отель')
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('3000000')
 await page.getByLabel('Длительность, ч', { exact: true }).fill('5')
 await page.getByLabel('Дата события', { exact: true }).fill('2026-09-25')
 expect((await search(page)).status).toBe('NO_MATCHES')
 await expect(cards(page)).toHaveCount(0)
 await page.getByLabel('Дата события', { exact: true }).fill('2026-09-23')
 expect((await search(page)).status).toBe('MATCHED')
 await expect(cards(page)).toHaveCount(1)
 await expect(cards(page)).toHaveAttribute('data-profile-id', 'HK-90012')
 await expect(page.locator('.date-comparison')).toContainText('В предыдущем запросе подходящих не было.')
 await expect(page.locator('.date-comparison')).toContainText('На новую дату подходят: 1; показаны: 1.')

 await page.getByLabel('Город', { exact: true }).selectOption('Алматы')
 await page.getByLabel('Кого ищем', { exact: true }).selectOption('Ведущий')
 await page.getByLabel('Бюджет, ₸', { exact: true }).fill('1000000')
 await page.getByLabel('Длительность, ч', { exact: true }).fill('')
 await page.getByLabel('Дата события', { exact: true }).fill('2026-09-30')
 await search(page)
 await expect(page.locator('[data-profile-id="HK-35215"]')).toBeVisible()
 await expect(page.locator('.date-comparison')).toHaveCount(0)
 await page.getByLabel('Дата события', { exact: true }).fill('2026-10-06')
 const updated = await search(page)
 expect(updated.eligible_ids).toContain('HK-35215')
 expect(updated.exclusions.some(exclusion => exclusion.id === 'HK-35215')).toBeFalsy()
 await expect(cards(page)).toHaveCount(3)
 await expect(page.locator('[data-profile-id="HK-35215"]')).toHaveCount(0)
 await expect(page.locator('.date-comparison')).toContainText('Кики: по-прежнему подходит, но не входит в первые три')
 await expect(page.locator('.date-comparison')).not.toContainText('Кики: занят')
})

test('метаданные demo и team явно подписывают происхождение каталога', async ({ page, request }) => {
 const response = await request.get('/api/catalog/meta')
 expect(response.ok()).toBeTruthy()
 const metadata = await response.json() as CatalogMetadata
 let origin: CatalogMetadata['origin'] = 'demo'
 // Test-only metadata substitution; the original dataset and server configuration remain intact.
 await page.route('**/api/catalog/meta', route => route.fulfill({ json: { ...metadata, origin } }))
 for (const variant of [
  { origin: 'demo', title: 'Демонстрационные синтетические данные', badge: 'ДЕМО' },
  { origin: 'team', title: 'Каталог команды', badge: 'КАТАЛОГ' },
 ] as const) {
  origin = variant.origin
  await openApplication(page)
  const banner = page.locator('.demo-banner')
  await expect(banner.locator('strong')).toHaveText(variant.title)
  await expect(banner.locator('.demo-label')).toHaveText(variant.badge)
  await expect(banner).toContainText(`Профилей: ${metadata.profile_count}.`)
  await expect(banner).not.toContainText('Исходный каталог')
  await expect(cards(page)).toHaveCount(0)
 }
})
