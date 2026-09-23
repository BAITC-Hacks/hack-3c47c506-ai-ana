import { test, expect } from '@playwright/test'

test('адаптивность и демонстрационные карточки', async ({ page }) => {
 const errors: string[] = []
 page.on('pageerror', e => errors.push(e.message))
 for (const width of [1440, 768, 390, 320]) {
  await page.setViewportSize({width,height:1000})
  await page.goto('/')
  await page.evaluate(() => document.fonts.ready)
  await expect(page.getByRole('heading', {name:'Ваше событие. Подходящие люди.'})).toBeVisible()
  await expect(page.locator('.contractor-card')).toHaveCount(3)
  const overflow = await page.evaluate(() => [...document.querySelectorAll('*')].filter(el => el.getBoundingClientRect().right > innerWidth).map(el => ({tag:el.tagName,cls:el.className,right:el.getBoundingClientRect().right})))
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), JSON.stringify({width,overflow})).toBeTruthy()
  await page.screenshot({path:`../docs/screenshots/prototype-${width}.png`,fullPage:true})
 }
 expect(errors).toEqual([])
})

test('цвет сохраняется, форма и раскрытые основания остаются', async ({ page }) => {
 await page.goto('/')
 await page.getByLabel('Бюджет, ₸', {exact:true}).fill('750000')
 await page.locator('summary').first().click()
 await page.getByRole('button',{name:'Оформление',exact:true}).click()
 for (const name of ['Зелёный','Фиолетовый','Оранжевый','Синий']) {
  await page.getByRole('button',{name,exact:true}).click()
  await expect(page.getByRole('button',{name,exact:true})).toHaveAttribute('aria-pressed','true')
 }
 await page.getByLabel('Свой цвет', {exact:true}).fill('#FFFFFF')
 expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--on-accent'))).toBe('#000000')
 await expect(page.getByLabel('Бюджет, ₸', {exact:true})).toHaveValue('750000')
 await expect(page.locator('details').first()).toHaveAttribute('open','')
 await page.getByLabel('Свой цвет', {exact:true}).fill('#000000')
 expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--on-accent'))).toBe('#FFFFFF')
 await page.getByLabel('Свой цвет', {exact:true}).fill('oops')
 await expect(page.getByText('Введите цвет в формате #RRGGBB.')).toBeVisible()
 await page.reload()
 await page.getByRole('button',{name:'Оформление',exact:true}).click()
 await expect(page.getByLabel('Свой цвет', {exact:true})).toHaveValue('#000000')
 await page.getByRole('button',{name:'Вернуть стандартный цвет'}).click()
 await expect(page.getByLabel('Свой цвет', {exact:true})).toHaveValue('#2563EB')
 await page.getByRole('button',{name:'Зелёный',exact:true}).click()
 await page.screenshot({path:'../docs/screenshots/appearance-green.png',fullPage:true})
})

test('валидация, загрузка и примеры состояний', async ({ page }) => {
 await page.goto('/')
 await page.getByLabel('Бюджет, ₸', {exact:true}).fill('-1')
 await page.getByRole('button',{name:'Посмотреть пример подбора'}).click()
 await expect(page.getByText('Укажите положительный бюджет в целых тенге')).toBeVisible()
 await page.getByLabel('Бюджет, ₸', {exact:true}).fill('1000000')
 await page.getByLabel('Дата события').fill('2027-01-01')
 await page.getByRole('button',{name:'Посмотреть пример подбора'}).click()
 await expect(page.getByText('Выберите дату с 23.09 по 31.12.2026')).toBeVisible()
 await page.getByLabel('Дата события').fill('2026-09-30')
 await page.getByRole('button',{name:'Посмотреть пример подбора'}).click()
 await expect(page.getByText('Форма проверена.',{exact:false})).toBeVisible()
 for (const [button,heading] of [['Нет подходящих','По этим условиям нет подходящих'],['Нет категории','В этом городе пока нет категории'],['Ошибка','Не удалось загрузить подбор'],['До поиска','Начнём с вашего события']]) {
  await page.getByRole('button',{name:button,exact:true}).click()
  await expect(page.getByRole('heading',{name:heading})).toBeVisible()
  await expect(page.locator('.contractor-card')).toHaveCount(0)
 }
})

test('недоступное хранилище не ломает оформление', async ({ page }) => {
 await page.addInitScript(() => { Object.defineProperty(window,'localStorage',{get(){throw new Error('Storage unavailable')}}) })
 await page.goto('/')
 await page.getByRole('button',{name:'Оформление',exact:true}).click()
 await page.getByRole('button',{name:'Зелёный',exact:true}).click()
 await expect(page.getByLabel('Свой цвет', {exact:true})).toHaveValue('#15803D')
 await expect(page.locator('.contractor-card')).toHaveCount(3)
})
