import { expect, test, type Route } from '@playwright/test'

test.setTimeout(60_000)

test('окно аккаунта получает Escape, а настройки оформления остаются рабочими', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: null, csrf_token: null } }))
  await page.goto('/')
  const appearanceTrigger = page.getByRole('button', { name: 'Оформление', exact: true })
  await appearanceTrigger.click()
  await expect(page.getByRole('region', { name: 'Настройки оформления' })).toBeVisible()
  await page.getByRole('button', { name: 'Войти в аккаунт', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('region', { name: 'Настройки оформления' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Войти в аккаунт', exact: true })).toBeFocused()

  const accent = () => page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--accent').trim().toUpperCase())
  for (const [name, color] of [['Синий', '#2563EB'], ['Зелёный', '#15803D'], ['Фиолетовый', '#7C3AED'], ['Оранжевый', '#C2410C']]) {
    await page.getByRole('button', { name, exact: true }).click()
    await expect.poll(accent).toBe(color)
    await expect(page.getByRole('button', { name, exact: true })).toHaveAttribute('aria-pressed', 'true')
  }
  await page.getByLabel('Свой цвет', { exact: true }).fill('#123456')
  await expect.poll(accent).toBe('#123456')
  await page.getByLabel('Свой цвет', { exact: true }).fill('#oops')
  await expect(page.getByText('Введите цвет в формате #RRGGBB.')).toBeVisible()
  await expect.poll(accent).toBe('#123456')
  await page.getByLabel('Выбрать акцентный цвет', { exact: true }).fill('#aabbcc')
  await expect.poll(accent).toBe('#AABBCC')
  await expect(page.getByLabel('Свой цвет', { exact: true })).toHaveValue('#aabbcc')
  await page.getByRole('button', { name: 'Вернуть стандартный цвет', exact: true }).click()
  await expect.poll(accent).toBe('#2563EB')
  await expect(page.getByLabel('Свой цвет', { exact: true })).toHaveValue('#2563EB')
  await page.keyboard.press('Escape')
  await expect(page.getByRole('region', { name: 'Настройки оформления' })).toHaveCount(0)
  await expect(appearanceTrigger).toBeFocused()
  await appearanceTrigger.click()
  await page.getByRole('button', { name: 'Закрыть настройки', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Настройки оформления' })).toHaveCount(0)
  await expect(appearanceTrigger).toBeFocused()
})


const accountUser = {
  id: 'controls-mock-user', email: 'controls@example.com', name: 'Айдана', city: 'Алматы', created_at: '2026-09-23T00:00:00Z',
}

test('запоздалый вход обновляет повторно открытое окно аккаунта', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: null, csrf_token: null } }))
  let captureRequest: (route: Route) => void = () => {}
  const pendingRequest = new Promise<Route>(resolve => { captureRequest = resolve })
  await page.route('**/api/auth/login', route => captureRequest(route))
  await page.goto('/')
  await page.getByRole('button', { name: 'Войти в аккаунт', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Email', { exact: true }).fill(accountUser.email)
  await dialog.getByLabel('Пароль', { exact: true }).fill('Пример пароля для проверки')
  await dialog.getByRole('button', { name: 'Войти', exact: true }).click()
  const request = await pendingRequest
  await page.getByRole('button', { name: 'Закрыть аккаунт', exact: true }).click()
  await page.getByRole('button', { name: 'Войти в аккаунт', exact: true }).click()
  await expect(dialog.getByRole('heading', { name: 'С возвращением' })).toBeVisible()
  await request.fulfill({ json: { user: accountUser, csrf_token: 'controls-mock-token' } })
  await expect(dialog.getByRole('heading', { name: 'Ваш профиль' })).toBeVisible()
  await expect(dialog.getByLabel('Имя', { exact: true })).toHaveValue(accountUser.name)
  await expect(dialog.getByLabel('Email', { exact: true })).toHaveValue(accountUser.email)
  await expect(dialog.getByRole('button', { name: 'Выйти из аккаунта', exact: true })).toBeEnabled()
})

test('запоздалое сохранение обновляет поля повторно открытого профиля', async ({ page }) => {
  await page.route('**/api/auth/me', route => route.fulfill({ json: { user: accountUser, csrf_token: 'controls-mock-token' } }))
  let captureRequest: (route: Route) => void = () => {}
  const pendingRequest = new Promise<Route>(resolve => { captureRequest = resolve })
  await page.route('**/api/auth/profile', route => captureRequest(route))
  await page.goto('/')
  await page.getByRole('button', { name: `Профиль: ${accountUser.name}`, exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Имя', { exact: true }).fill('Айдана Серик')
  await dialog.getByLabel('Город', { exact: false }).fill('Астана')
  await dialog.getByRole('button', { name: 'Сохранить изменения', exact: true }).click()
  const request = await pendingRequest
  await page.getByRole('button', { name: 'Закрыть аккаунт', exact: true }).click()
  await page.getByRole('button', { name: `Профиль: ${accountUser.name}`, exact: true }).click()
  await expect(dialog.getByLabel('Имя', { exact: true })).toHaveValue(accountUser.name)
  await request.fulfill({ json: { user: { ...accountUser, name: 'Айдана Серик', city: 'Астана' }, csrf_token: 'controls-mock-token' } })
  await expect(dialog.getByLabel('Имя', { exact: true })).toHaveValue('Айдана Серик')
  await expect(dialog.getByLabel('Город', { exact: false })).toHaveValue('Астана')
  await expect(page.getByRole('button', { name: 'Профиль: Айдана Серик', exact: true })).toHaveCount(1)
  await dialog.getByLabel('Имя', { exact: true }).fill('Новое имя')
  await dialog.getByLabel('Город', { exact: false }).fill('Алматы')
  await expect(dialog.getByLabel('Имя', { exact: true })).toHaveValue('Новое имя')
})
