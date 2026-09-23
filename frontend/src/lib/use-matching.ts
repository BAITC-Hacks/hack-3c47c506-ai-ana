import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError, getCatalogMetadata, getRecommendations } from './api/client'
import { sameQuery } from './matching-form'
import type { CatalogMetadata, ErrorIssue, RecommendationRequest, RecommendationResponse } from './api/generated'

export type RequestFailure = { message: string; issues: ErrorIssue[]; validation: boolean }

function failure(error: unknown, timedOut: boolean): RequestFailure {
  if (timedOut) return { message: 'Сервер долго не отвечает. Повторите подбор.', issues: [], validation: false }
  if (error instanceof ApiError) return { message: error.message, issues: error.issues, validation: error.code === 'INVALID_QUERY' }
  return { message: 'Не удалось связаться с сервером. Проверьте соединение и повторите попытку.', issues: [], validation: false }
}

export function useCatalog() {
  const [metadata, setMetadata] = useState<CatalogMetadata | null>(null)
  const [error, setError] = useState<RequestFailure | null>(null)
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 12000)
    setError(null)
    getCatalogMetadata(controller.signal).then(value => { if (active) setMetadata(value) }).catch(cause => {
      if (active) setError(failure(cause, timedOut))
    }).finally(() => clearTimeout(timeout))
    return () => { active = false; controller.abort(); clearTimeout(timeout) }
  }, [attempt])
  return { metadata, error, retry: () => setAttempt(value => value + 1) }
}

type MatchState =
  | { status: 'initial' | 'editing' | 'loading' }
  | { status: 'error' | 'validation'; error: RequestFailure }
  | { status: 'ready'; result: RecommendationResponse; previous: RecommendationResponse | null }

export function useMatching() {
  const [state, setState] = useState<MatchState>({ status: 'initial' })
  const active = useRef<AbortController | null>(null)
  const sequence = useRef(0)
  const previous = useRef<RecommendationResponse | null>(null)
  const comparison = useRef<RecommendationResponse | null>(null)
  const cancel = useCallback(() => { sequence.current += 1; active.current?.abort() }, [])
  useEffect(() => cancel, [cancel])

  const submit = useCallback(async (query: RecommendationRequest): Promise<RequestFailure | null> => {
    cancel()
    const requestId = sequence.current
    const controller = new AbortController()
    active.current = controller
    let timedOut = false
    const timeout = window.setTimeout(() => { timedOut = true; controller.abort() }, 12000)
    // A new request immediately removes the previous cards from the screen.
    setState({ status: 'loading' })
    try {
      const result = await getRecommendations(query, controller.signal)
      if (requestId !== sequence.current) return null
      if (!previous.current || !sameQuery(previous.current.query, result.query)
          || previous.current.catalog_version !== result.catalog_version
          || previous.current.ranking_version !== result.ranking_version) {
        comparison.current = previous.current
      }
      setState({ status: 'ready', result, previous: comparison.current })
      previous.current = result
      return null
    } catch (cause) {
      if (requestId !== sequence.current) return null
      const error = failure(cause, timedOut)
      setState({ status: error.validation ? 'validation' : 'error', error })
      return error
    } finally {
      clearTimeout(timeout)
    }
  }, [cancel])

  const invalidate = useCallback(() => {
    cancel()
    setState({ status: 'validation', error: { message: 'Проверьте отмеченные поля формы. Подбор обновится после исправления.', issues: [], validation: true } })
  }, [cancel])
  const beginEditing = useCallback(() => {
    cancel()
    setState({ status: 'editing' })
  }, [cancel])
  return { state, submit, invalidate, beginEditing }
}
