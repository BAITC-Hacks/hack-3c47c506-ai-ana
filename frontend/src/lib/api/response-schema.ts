import { z } from 'zod'
import type { CatalogMetadata, RecommendationResponse } from './generated'

const count = z.number().int().nonnegative()
const origin = z.enum(['original', 'team', 'demo'])
const calendarDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/).refine(value => {
  const timestamp = Date.parse(value)
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value
})
const evidenceValue = z.union([z.string(), z.number(), z.boolean(), z.array(z.string()), z.null()])
const evidence = z.object({
  code: z.string(),
  field: z.string(),
  profile_value: evidenceValue.optional(),
  requested_value: evidenceValue.optional(),
  quote: z.string().nullable().optional(),
  text: z.string(),
  display_is_cleaned: z.boolean().optional(),
})
const warning = z.object({
  code: z.string(),
  message: z.string(),
  evidence: evidence.nullable().optional(),
  profile_id: z.string().nullable().optional(),
})
const rejectionCode = z.enum([
  'BUSY_ON_DATE',
  'UNSUPPORTED_FORMAT',
  'OVER_BUDGET',
  'UNSUPPORTED_LANGUAGE',
  'DURATION_EXCEEDED',
])

export const catalogMetadataSchema: z.ZodType<CatalogMetadata> = z.object({
  status: z.literal('ready'),
  catalog_version: z.string(),
  source_sha256: z.string(),
  origin,
  profile_count: count,
  calendar: z.object({ start: calendarDate, end: calendarDate }),
  dictionaries: z.object({
    city: z.array(z.string()),
    categories: z.array(z.string()),
    event_formats: z.array(z.string()),
    languages: z.array(z.string()),
  }),
  quality: z.object({
    synthetic: count,
    city_imputed: count,
    price_imputed: count,
    null_max_hours: count,
  }),
  city_counts: z.record(z.string(), count),
  category_counts: z.record(z.string(), count),
})

export const recommendationResponseSchema: z.ZodType<RecommendationResponse> = z.object({
  status: z.enum(['MATCHED', 'CATEGORY_UNAVAILABLE', 'NO_MATCHES']),
  message: z.string(),
  query: z.object({
    city: z.string(),
    event_date: calendarDate,
    event_format: z.string(),
    category: z.string(),
    budget_kzt: z.number().int().positive(),
    duration_hours: z.string().nullable().optional(),
    language: z.string().nullable().optional(),
  }),
  catalog_version: z.string(),
  ranking_version: z.string(),
  explanation_version: z.string(),
  counts: z.object({ group: count, matched: count, shown: count }),
  rejections: z.record(z.string(), count),
  cards: z.array(z.object({
    id: z.string(),
    anon_name: z.string(),
    category: z.string(),
    categories: z.array(z.string()),
    city: z.string(),
    price_from_kzt: z.number().int().positive(),
    price_label: z.string(),
    event_date: calendarDate,
    availability_text: z.string(),
    languages: z.array(z.string()),
    max_hours: z.string().nullable(),
    duration_text: z.string(),
    explanation: z.string(),
    evidence: z.array(evidence),
    synthetic: z.boolean(),
    city_imputed: z.boolean(),
    price_imputed: z.boolean(),
    origin,
    labels: z.array(z.string()),
    warnings: z.array(warning),
  })).max(3),
  warnings: z.array(warning),
  eligible_ids: z.array(z.string()),
  exclusions: z.array(z.object({
    id: z.string(),
    reasons: z.array(rejectionCode),
    primary_reason: rejectionCode,
  })),
})
