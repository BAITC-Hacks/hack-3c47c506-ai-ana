import { z } from 'zod'

const accountUserSchema = z.object({
  id: z.string(),
  email: z.string(),
  name: z.string(),
  city: z.string(),
  created_at: z.string(),
})
const sessionSchema = z.object({
  user: accountUserSchema.nullable(),
  csrf_token: z.string().nullable(),
}).refine(value => value.user === null ? value.csrf_token === null : Boolean(value.csrf_token))
const errorSchema = z.object({
  code: z.string(), message: z.string(),
  issues: z.array(z.object({ field: z.string(), message: z.string() })).optional(),
})

export type AccountUser = z.infer<typeof accountUserSchema>
export type AccountSession = z.infer<typeof sessionSchema>
export type AccountInput = { email: string; password: string; name: string; city: string }

export class AccountError extends Error {
  constructor(
    message: string,
    readonly status = 0,
    readonly issues: { field: string; message: string }[] = [],
  ) {
    super(message)
    this.name = 'AccountError'
  }
}

async function requestSession(path: string, options: RequestInit = {}): Promise<AccountSession> {
  let response: Response
  try {
    response = await fetch(`/api/auth/${path}`, {
      ...options,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: options.signal
        ? AbortSignal.any([options.signal, AbortSignal.timeout(12_000)])
        : AbortSignal.timeout(12_000),
    })
  } catch (error) {
    if (options.signal?.aborted) throw error
    throw new AccountError('Не удалось связаться с сервером. Проверьте соединение и попробуйте ещё раз.')
  }
  const payload: unknown = await response.json().catch(() => null)
  if (!response.ok) {
    const parsed = errorSchema.safeParse(payload)
    throw new AccountError(
      parsed.success ? parsed.data.message : 'Не удалось выполнить действие. Попробуйте ещё раз.',
      response.status,
      parsed.success ? parsed.data.issues ?? [] : [],
    )
  }
  const parsed = sessionSchema.safeParse(payload)
  if (!parsed.success) throw new AccountError('Не удалось прочитать ответ сервера. Попробуйте ещё раз.')
  return parsed.data
}

export const getAccountSession = (signal?: AbortSignal) => requestSession('me', { signal })

export function updateAccountSession(
  action: 'login' | 'register' | 'profile' | 'logout',
  input: Partial<AccountInput>,
  csrfToken: string | null,
) {
  return requestSession(action, {
    method: action === 'profile' ? 'PATCH' : 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-Requested-With': 'AI-ANA',
      ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {}),
    },
    body: JSON.stringify(input),
  })
}
