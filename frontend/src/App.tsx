import type { ReactNode } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { ArrowRight, ArrowUpRight, Check, MapPin, Search, Info } from 'lucide-react'
import { Button } from './components/ui/button'
import { BrandLogo } from './components/brand/BrandLogo'
import { AppearanceSettings } from './components/AppearanceSettings'
import { Account } from './components/Account'
import { RecommendationCard } from './components/RecommendationCard'
import type { CatalogMetadata, RecommendationResponse } from './lib/api/generated'
import { displayDate, exampleQueries, formSchema, initialValues, sameQuery, toRequest } from './lib/matching-form'
import type { FormValues } from './lib/matching-form'
import { useCatalog, useMatching } from './lib/use-matching'

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1)

function DateComparison({ current, previous }: { current: RecommendationResponse; previous: RecommendationResponse | null }) {
  if (!previous || previous.query.event_date === current.query.event_date || !sameQuery(previous.query, current.query, true)) return null
  if (previous.catalog_version !== current.catalog_version || previous.ranking_version !== current.ranking_version) {
    return <p className="submission-note">Каталог или порядок подбора обновился. Изменения результатов нельзя объяснить только сменой даты.</p>
  }
  const removed = previous.cards.filter(card => !current.cards.some(next => next.id === card.id))
  return <div className="date-comparison" aria-label="Что изменилось при смене даты">
    <h3>Что изменилось на {displayDate(current.query.event_date)}</h3>
    {!previous.cards.length ? <p>В предыдущем запросе подходящих не было. На новую дату подходят: {current.counts.matched}; показаны: {current.counts.shown}.</p> : removed.length ? <ul>{removed.map(card => {
      const exclusion = current.exclusions.find(item => item.id === card.id)
      const reason = exclusion?.reasons.includes('BUSY_ON_DATE')
        ? 'занят на новую дату по календарю датасета.'
        : current.eligible_ids.includes(card.id)
          ? 'по-прежнему подходит, но не входит в первые три по цене и порядку каталога.'
          : 'не проходит условия нового запроса по данным сервера.'
      return <li key={card.id}>{card.anon_name}: {reason}</li>
    })}</ul> : <p>Все ранее показанные подрядчики остаются в выдаче. Подходящих на новую дату: {current.counts.matched}.</p>}
    <p>Сравнение с {displayDate(previous.query.event_date)}. Остальные условия сохранены.</p>
  </div>
}

function Results({ result, previous }: { result: RecommendationResponse; previous: RecommendationResponse | null }) {
  const query = result.query
  const context = [query.city, query.category, capitalize(query.event_format), displayDate(query.event_date), `${query.budget_kzt.toLocaleString('ru-RU')} ₸`, query.duration_hours ? `${Number(query.duration_hours).toLocaleString('ru-RU')} ч` : null, query.language].filter(Boolean).join(' · ')
  return <>
    <p className="example-context">Условия подбора: {context}</p>
    <DateComparison current={result} previous={previous}/>
    {result.status === 'MATCHED' ? <>
      <div className="result-summary"><span><Check size={15} aria-hidden="true"/> Показаны {result.counts.shown} из {result.counts.matched} подходящих</span><span>По начальной цене</span></div>
      <div className="cards">{result.cards.map((card, index) => <RecommendationCard key={card.id} card={card} index={index}/>)}</div>
      <details className="selection-diagnostics"><summary>Как получился этот список</summary><p>{result.message}</p><p>При одинаковой цене порядок определяется идентификатором профиля. Это не рейтинг качества.</p></details>
      {result.counts.shown < 3 && <p className="submission-note">{result.message}</p>}
    </> : <div className="empty-state result-state" data-status={result.status}>
      <Search size={30} aria-hidden="true"/>
      <h3>{result.status === 'CATEGORY_UNAVAILABLE' ? 'В этом городе пока нет категории' : 'По этим условиям нет подходящих'}</h3>
      <p>{result.message}</p>
      <p>{result.status === 'CATEGORY_UNAVAILABLE' ? 'Выберите другой город или категорию в форме.' : 'Измените параметры в форме и повторите подбор. Доступность зависит от даты.'}</p>
    </div>}
    {result.warnings.filter(warning => !warning.profile_id).map((warning, index) => <p className="result-footnote" key={`${warning.code}-${index}`}><Info size={15} aria-hidden="true"/>{warning.message}</p>)}
  </>
}

function Matcher({ metadata }: { metadata: CatalogMetadata }) {
  const form = useForm<FormValues>({ resolver: zodResolver(formSchema(metadata)), defaultValues: initialValues(metadata) })
  const { state, submit, invalidate } = useMatching()
  const values = form.watch()
  const edited = state.status === 'ready' && !sameQuery(state.result.query, toRequest(values))
  const loading = state.status === 'loading'
  const examples = exampleQueries(metadata)

  async function search(input: FormValues) {
    form.clearErrors()
    const error = await submit(toRequest(input))
    if (!error?.validation) return
    // Do not attach errors from a submitted query to fields the user has since changed.
    if (!sameQuery(toRequest(input), toRequest(form.getValues()))) return
    const fields = Object.keys(input)
    let first: keyof FormValues | undefined
    for (const issue of error.issues) {
      if (!fields.includes(issue.field)) continue
      const name = issue.field as keyof FormValues
      form.setError(name, { type: 'server', message: issue.message })
      first ??= name
    }
    if (first) form.setFocus(first)
  }

  function field(name: keyof FormValues, label: string, children: ReactNode) {
    const error = form.formState.errors[name]
    return <div className="field"><label htmlFor={name}>{label}</label>{children}{error && <p className="field-error" id={`${name}-error`}>{error.message}</p>}</div>
  }
  const attrs = (name: keyof FormValues) => ({ id: name, 'aria-invalid': !!form.formState.errors[name], 'aria-describedby': form.formState.errors[name] ? `${name}-error` : undefined, ...form.register(name) })
  return <div className="workspace">
    <aside className="form-panel"><div className="panel-heading"><span className="step">01</span><div><h2>О вашем событии</h2><p>Начнём с самого важного</p></div></div>
      <form noValidate onSubmit={form.handleSubmit(search, invalidate)}>
        <div className="form-fields">
          {field('city', 'Город', <select {...attrs('city')}>{metadata.dictionaries.city.map(value => <option key={value}>{value}</option>)}</select>)}
          {field('category', 'Кого ищем', <select {...attrs('category')}>{metadata.dictionaries.categories.map(value => <option key={value}>{value}</option>)}</select>)}
          <div className="field-row">
            {field('event_date', 'Дата события', <input type="date" min={metadata.calendar.start} max={metadata.calendar.end} {...attrs('event_date')}/>)}
            {field('event_format', 'Формат', <select {...attrs('event_format')}>{metadata.dictionaries.event_formats.map(value => <option key={value} value={value}>{capitalize(value)}</option>)}</select>)}
          </div>
          {field('budget_kzt', 'Бюджет, ₸', <input type="number" min="1" max={Number.MAX_SAFE_INTEGER} step="1" placeholder="Например, 1000000" {...attrs('budget_kzt')}/>)}
          <p className="input-hint">Сравниваем с начальной ценой за мероприятие.<br/>Даты: {displayDate(metadata.calendar.start)}–{displayDate(metadata.calendar.end)}.</p>
          <div className="optional-heading"><span>Дополнительно</span><span>необязательно</span></div>
          <div className="field-row">
            {field('duration_hours', 'Длительность, ч', <input type="number" min="0" step="any" placeholder="Не указана" {...attrs('duration_hours')}/>)}
            {field('language', 'Язык', <select {...attrs('language')}><option value="">Любой</option>{metadata.dictionaries.languages.map(value => <option key={value} value={value}>{capitalize(value)}</option>)}</select>)}
          </div>
        </div>
        <div className="form-bottom"><Button type="submit" className="w-full">{loading ? 'Обновить подбор' : 'Подобрать подрядчиков'}<ArrowRight size={17} aria-hidden="true"/></Button><p>{loading ? 'Новый запрос заменит текущий.' : <>Без заявок и бронирования.<br/>Только помощь с выбором.</>}</p></div>
      </form>
    </aside>
    <section className="results" aria-label="Результат подбора">
      <div className="results-top"><div><div className="eyebrow small">ВАШ КОРОТКИЙ СПИСОК</div><h2>{state.status === 'ready' && state.result.status === 'MATCHED' ? 'Есть из кого выбрать' : 'Найдём подходящие варианты'}</h2></div><span className="result-counter">До 3 вариантов</span></div>
      {examples.length > 0 && <div className="preview-controls" aria-label="Примеры запросов"><span>Попробуйте:</span>{examples.map(example => <button key={example.label} onClick={() => { form.reset(example.values); void search(example.values) }}>{example.label}</button>)}</div>}
      {edited && <p className="submission-note" role="status">Параметры изменены. Нажмите «Подобрать подрядчиков», чтобы обновить результат. Ниже показан предыдущий запрос.</p>}
      <div aria-live="polite" aria-busy={loading}>
        {state.status === 'initial' && <div className="empty-state result-state" data-status="initial"><Search size={30} aria-hidden="true"/><h3>Начнём с вашего события</h3><p>Укажите параметры и нажмите «Подобрать подрядчиков». Покажем до трёх вариантов из каталога с основаниями выбора.</p></div>}
        {loading && <div className="empty-state result-state" data-status="loading"><Search size={30} aria-hidden="true"/><h3>Подбираем подрядчиков</h3><p>Проверяем условия и занятость на выбранную дату.</p></div>}
        {(state.status === 'error' || state.status === 'validation') && <div className="empty-state result-state" data-status={state.status} role="alert"><Info size={30} aria-hidden="true"/><h3>{state.status === 'validation' ? 'Проверьте параметры события' : 'Не удалось загрузить подбор'}</h3><p>{state.error.message}</p>{state.error.issues.length > 0 && <ul className="error-issues">{state.error.issues.filter(issue => !form.formState.errors[issue.field as keyof FormValues]).map((issue, index) => <li key={index}>{issue.message}</li>)}</ul>}<p>Исправьте параметры при необходимости и нажмите «Подобрать подрядчиков».</p></div>}
        {state.status === 'ready' && <Results result={state.result} previous={state.previous}/>}
      </div>
    </section>
  </div>
}

export default function App() {
  const { metadata, error, retry } = useCatalog()
  return <>
    <header className="site-header"><div className="header-inner"><BrandLogo/><div className="header-actions"><span className="header-location"><MapPin size={15} aria-hidden="true"/> Казахстан</span><AppearanceSettings/><Account/></div></div></header>
    <main className="page">
      <section className="hero"><div><div className="eyebrow"><span/> ПОДБОР ПОДРЯДЧИКОВ ДЛЯ СОБЫТИЙ</div><h1>Ваше событие.<br/><span>Подходящие люди.</span></h1><p>Расскажите о мероприятии — сравните до трёх вариантов<br className="desktop-break"/> и узнайте, почему каждый из них вам подходит.</p></div><div className="hero-note"><span className="note-number">01 — 03</span><span>Меньше поиска.<br/>Больше ясности в выборе.</span><ArrowUpRight size={24} aria-hidden="true"/></div></section>
      {metadata ? <>
        <div className="demo-banner"><Info size={18} aria-hidden="true"/><p><strong>{metadata.origin === 'demo' ? 'Демонстрационные синтетические данные' : metadata.origin === 'team' ? 'Каталог команды' : 'Исходный каталог'}</strong><span>Профилей: {metadata.profile_count}. {metadata.origin === 'original' ? 'Имена анонимизированы. ' : ''}Начальные цены и занятость — по данным набора.</span></p><span className="demo-label">{metadata.origin === 'demo' ? 'ДЕМО' : 'КАТАЛОГ'}</span></div>
        <Matcher metadata={metadata}/>
      </> : error ? <div className="empty-state catalog-error" role="alert"><Info size={30} aria-hidden="true"/><h2>Не удалось загрузить каталог</h2><p>{error.message}</p><Button variant="outline" onClick={retry}>Повторить загрузку</Button></div> : <div className="empty-state" role="status"><h2>Загружаем каталог</h2><p>Получаем доступные города, категории и даты.</p></div>}
      <section className="principles" aria-label="Как устроен выбор"><div><span>01 / УСЛОВИЯ</span><h3>Сначала — ваши параметры</h3><p>Город, дата и бюджет задают границы поиска.</p></div><div><span>02 / ПОНЯТНЫЙ ПОРЯДОК</span><h3>Цена, а не скрытый рейтинг</h3><p>Подходящие варианты — по начальной цене.</p></div><div><span>03 / ОБЪЯСНЕНИЯ</span><h3>У каждого выбора есть причина</h3><p>Конкретные факты вместо общих обещаний.</p></div></section>
      <footer><span>AI-ANA <span className="footer-separator">/</span> Событие начинается с выбора</span><span>HackAlem · 2026</span></footer>
    </main>
  </>
}
