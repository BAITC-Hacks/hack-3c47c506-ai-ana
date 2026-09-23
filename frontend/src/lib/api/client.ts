import type {
  CatalogMetadata,
  ErrorResponse,
  RecommendationRequest,
  RecommendationResponse,
} from './generated'
import type { ZodType } from 'zod'
import { catalogMetadataSchema, recommendationResponseSchema } from './response-schema'

export class ApiError extends Error {
  readonly status: number
  readonly code: ErrorResponse['code'] | 'INVALID_RESPONSE'
  readonly issues: NonNullable<ErrorResponse['issues']>

  constructor(status: number, error: ErrorResponse) {
    super(error.message)
    this.name = 'ApiError'
    this.status = status
    this.code = error.code
    this.issues = error.issues ?? []
  }
}

function isApiError(value: unknown): value is ErrorResponse {
  if (typeof value !== 'object' || value === null) return false
  const error = value as Record<string, unknown>
  return ['INVALID_QUERY', 'CATALOG_LOAD_FAILED', 'INTERNAL_ERROR'].includes(String(error.code))
    && typeof error.message === 'string'
    && (error.issues === undefined || (Array.isArray(error.issues) && error.issues.every(issue =>
      typeof issue === 'object' && issue !== null
      && typeof issue.field === 'string' && typeof issue.message === 'string')))
}

async function request<T>(path: string, options: RequestInit, schema: ZodType<T>): Promise<T> {
  const response = await fetch(path, options)
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    throw new ApiError(response.status, {
      code: 'INTERNAL_ERROR',
      message: 'Сервер вернул ответ в неизвестном формате. Повторите запрос позже.',
    })
  }
  if (!response.ok) {
    throw new ApiError(response.status, isApiError(payload) ? payload : {
      code: 'INTERNAL_ERROR', message: 'Сервис подбора временно недоступен.',
    })
  }
  if (!schema.safeParse(payload).success) {
    throw new ApiError(response.status, {
      code: 'INTERNAL_ERROR',
      message: 'Сервер вернул ответ в неизвестном формате. Повторите запрос позже.',
    })
  }
  // Validate without transforming the response or removing additional API fields.
  return payload as T
}

export function getCatalogMetadata(signal?: AbortSignal): Promise<CatalogMetadata> {
  return request('/api/catalog/meta', { signal }, catalogMetadataSchema)
}

export function getRecommendations(
  query: RecommendationRequest,
  signal?: AbortSignal,
): Promise<RecommendationResponse> {
  return request('/api/recommendations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(query),
    signal,
  }, recommendationResponseSchema)
}
