import { z } from 'zod'
import type { CatalogMetadata, RecommendationQuery, RecommendationRequest } from './api/generated'

export type FormValues = {
  city: string
  category: string
  event_format: string
  event_date: string
  budget_kzt: string
  duration_hours: string
  language: string
}

export function displayDate(value: string) {
  return value.split('-').reverse().join('.')
}

export function formSchema(meta: CatalogMetadata) {
  const member = (values: string[], message: string) => z.string().refine(value => values.includes(value), message)
  return z.object({
    city: member(meta.dictionaries.city, 'Выберите город из каталога'),
    category: member(meta.dictionaries.categories, 'Выберите категорию из каталога'),
    event_format: member(meta.dictionaries.event_formats, 'Выберите формат мероприятия'),
    event_date: z.string().refine(value => /^\d{4}-\d{2}-\d{2}$/.test(value)
      && Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value
      && value >= meta.calendar.start && value <= meta.calendar.end,
    `Выберите дату с ${displayDate(meta.calendar.start)} по ${displayDate(meta.calendar.end)}`),
    budget_kzt: z.string().refine(value => /^\d+$/.test(value) && Number.isSafeInteger(Number(value)) && Number(value) > 0,
      'Укажите положительный бюджет в целых тенге'),
    duration_hours: z.string().refine(value => value === '' || (/^(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?$/i.test(value)
      && Number.isFinite(Number(value)) && Number(value) > 0), 'Укажите длительность больше нуля'),
    language: member(['', ...meta.dictionaries.languages], 'Выберите язык из каталога'),
  })
}

export function initialValues(meta: CatalogMetadata): FormValues {
  const prefer = (values: string[], wanted: string) => values.includes(wanted) ? wanted : values[0] ?? ''
  return {
    city: prefer(meta.dictionaries.city, 'Алматы'), category: prefer(meta.dictionaries.categories, 'Ведущий'),
    event_format: prefer(meta.dictionaries.event_formats, 'корпоратив'),
    event_date: '2026-09-30' >= meta.calendar.start && '2026-09-30' <= meta.calendar.end ? '2026-09-30' : meta.calendar.start,
    budget_kzt: '1000000', duration_hours: '', language: '',
  }
}

export function toRequest(values: FormValues): RecommendationRequest {
  return { ...values, budget_kzt: Number(values.budget_kzt), duration_hours: values.duration_hours === '' ? null : Number(values.duration_hours), language: values.language || null }
}

export function sameQuery(left: RecommendationQuery | RecommendationRequest, right: RecommendationQuery | RecommendationRequest, ignoreDate = false) {
  return left.city === right.city && left.category === right.category && left.event_format === right.event_format
    && (ignoreDate || left.event_date === right.event_date) && left.budget_kzt === right.budget_kzt
    && (left.language || null) === (right.language || null)
    && (left.duration_hours == null ? null : Number(left.duration_hours)) === (right.duration_hours == null ? null : Number(right.duration_hours))
}

export function exampleQueries(meta: CatalogMetadata): { label: string; values: FormValues }[] {
  const base = initialValues(meta)
  return [
    { label: 'Ведущие в Алматы', values: { ...base, city: 'Алматы', category: 'Ведущий', event_format: 'корпоратив', event_date: '2026-09-30' } },
    { label: 'Редкая категория', values: { ...base, city: 'Алматы', category: 'Декоратор', event_format: 'корпоратив', event_date: '2026-09-23', budget_kzt: '2500000', duration_hours: '5' } },
    { label: 'Небольшой бюджет', values: { ...base, city: 'Алматы', category: 'Ведущий', event_format: 'корпоратив', event_date: '2026-09-30', budget_kzt: '100000' } },
    { label: 'Декораторы в Астане', values: { ...base, city: 'Астана', category: 'Декоратор', event_format: 'корпоратив', event_date: '2026-09-23', budget_kzt: '2500000' } },
  ].filter(example => formSchema(meta).safeParse(example.values).success)
}
