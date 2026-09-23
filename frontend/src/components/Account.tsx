import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { Check, Eye, EyeOff, LogOut, UserRound, X } from 'lucide-react'
import { Button } from './ui/button'
import { AccountError, getAccountSession, updateAccountSession } from '../lib/api/auth'
import type { AccountInput, AccountSession } from '../lib/api/auth'

type AccountView = 'login' | 'register' | 'profile'
type FieldErrors = Partial<Record<keyof AccountInput, string>>
const emptySession: AccountSession = { user: null, csrf_token: null }

function AccountDialog({
  session, initialError, onSession, onClose,
}: {
  session: AccountSession
  initialError: string
  onSession: (session: AccountSession) => void
  onClose: (message?: string) => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  const formRef = useRef<HTMLFormElement>(null)
  const [view, setView] = useState<AccountView>(session.user ? 'profile' : 'login')
  const [values, setValues] = useState<AccountInput>({
    email: session.user?.email ?? '', password: '', name: session.user?.name ?? '', city: session.user?.city ?? '',
  })
  const [errors, setErrors] = useState<FieldErrors>({})
  const [error, setError] = useState(initialError)
  const [success, setSuccess] = useState('')
  const [pending, setPending] = useState(false)
  const [passwordVisible, setPasswordVisible] = useState(false)
  const mounted = useRef(true)
  const busy = useRef(false)

  useEffect(() => {
    mounted.current = true
    const dialog = dialogRef.current
    dialog?.showModal()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      mounted.current = false
      dialog?.close()
      document.body.style.overflow = previousOverflow
    }
  }, [])

  useEffect(() => {
    const firstInput = formRef.current?.querySelector<HTMLInputElement>('input:not([readonly])')
    firstInput?.focus()
  }, [view])

  function changeView(next: AccountView) {
    setView(next)
    setValues(current => ({ ...current, password: '' }))
    setErrors({})
    setError('')
    setSuccess('')
    setPasswordVisible(false)
  }

  function fieldProps(field: keyof AccountInput) {
    return {
      id: `account-${field}`,
      name: field,
      value: values[field],
      onChange: (event: ChangeEvent<HTMLInputElement>) => {
        setValues(current => ({ ...current, [field]: event.target.value }))
        setErrors(current => ({ ...current, [field]: undefined }))
        setSuccess('')
      },
      'aria-invalid': Boolean(errors[field]),
      'aria-describedby': errors[field] ? `account-${field}-error` : field === 'password' && view === 'register' ? 'account-password-hint' : undefined,
    }
  }

  function showFieldError(field: keyof AccountInput) {
    return errors[field] && <p className="field-error" id={`account-${field}-error`}>{errors[field]}</p>
  }

  function focusError(fieldErrors: FieldErrors) {
    const field = Object.keys(fieldErrors)[0]
    if (field) formRef.current?.querySelector<HTMLInputElement>(`[name="${field}"]`)?.focus()
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy.current) return
    const nextErrors: FieldErrors = {}
    if (view !== 'profile') {
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email.trim())) nextErrors.email = 'Укажите email, например name@example.com.'
      if (!values.password) nextErrors.password = 'Введите пароль.'
      else if (view === 'register' && [...values.password].length < 15) nextErrors.password = 'В пароле должно быть не менее 15 символов.'
      else if ([...values.password].length > 128) nextErrors.password = 'В пароле должно быть не более 128 символов.'
    }
    if (view !== 'login') {
      if (values.name.trim().length < 2) nextErrors.name = 'Укажите имя: не менее 2 символов.'
      else if (values.name.trim().length > 80) nextErrors.name = 'Имя должно быть не длиннее 80 символов.'
      if (values.city.trim().length > 80) nextErrors.city = 'Название города должно быть не длиннее 80 символов.'
    }
    setErrors(nextErrors)
    setError('')
    setSuccess('')
    if (Object.keys(nextErrors).length) {
      focusError(nextErrors)
      return
    }
    busy.current = true
    setPending(true)
    try {
      const input = view === 'login'
        ? { email: values.email.trim(), password: values.password }
        : view === 'register'
          ? { ...values, email: values.email.trim(), name: values.name.trim(), city: values.city.trim() }
          : { name: values.name.trim(), city: values.city.trim() }
      const next = await updateAccountSession(view, input, session.csrf_token)
      onSession(next)
      if (!mounted.current) return
      setValues({ email: next.user?.email ?? '', password: '', name: next.user?.name ?? '', city: next.user?.city ?? '' })
      setSuccess(view === 'profile' ? 'Профиль сохранён.' : view === 'register' ? 'Аккаунт создан. Добро пожаловать!' : 'Вы вошли в аккаунт.')
      setView('profile')
      setPasswordVisible(false)
    } catch (caught) {
      if (!mounted.current) return
      const failure = caught instanceof AccountError ? caught : new AccountError('Не удалось выполнить действие. Попробуйте ещё раз.')
      if (failure.status === 401 && view === 'profile') {
        onSession(emptySession)
        setValues(current => ({ ...current, password: '' }))
        setView('login')
        setError('Сессия закончилась. Войдите снова, чтобы изменить профиль.')
      } else {
        const fieldErrors: FieldErrors = {}
        for (const issue of failure.issues) {
          if (['name', 'email', 'password', 'city'].includes(issue.field)) fieldErrors[issue.field as keyof AccountInput] = issue.message
        }
        setErrors(fieldErrors)
        setError(failure.message)
        focusError(fieldErrors)
      }
    } finally {
      busy.current = false
      if (mounted.current) setPending(false)
    }
  }

  async function logout() {
    if (busy.current) return
    busy.current = true
    setPending(true)
    setError('')
    setSuccess('')
    try {
      const next = await updateAccountSession('logout', {}, session.csrf_token)
      onSession(next)
      if (mounted.current) onClose('Вы вышли из аккаунта.')
    } catch (caught) {
      if (!mounted.current) return
      if (caught instanceof AccountError && caught.status === 401) {
        onSession(emptySession)
        onClose('Вы вышли из аккаунта.')
      } else {
        setError(caught instanceof Error ? caught.message : 'Не удалось выйти. Попробуйте ещё раз.')
      }
    } finally {
      busy.current = false
      if (mounted.current) setPending(false)
    }
  }

  const title = view === 'profile' ? 'Ваш профиль' : view === 'register' ? 'Создать аккаунт' : 'С возвращением'
  return <dialog ref={dialogRef} className="account-dialog" aria-labelledby="account-title" aria-describedby="account-description"
    onCancel={event => { event.preventDefault(); onClose() }}
    onKeyDown={event => {
      if (event.key !== 'Tab') return
      const controls = [...event.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled)')]
      const first = controls[0]
      const last = controls.at(-1)
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
    }}>
    <div className="account-dialog-heading">
      <span className="account-emblem" aria-hidden="true"><UserRound size={22}/></span>
      <Button type="button" variant="ghost" size="sm" aria-label="Закрыть аккаунт" onClick={() => onClose()}><X size={20} aria-hidden="true"/></Button>
    </div>
    <h2 id="account-title">{title}</h2>
    <p id="account-description" className="account-description">{view === 'profile'
      ? 'Здесь можно обновить имя и город.'
      : view === 'register' ? 'Несколько деталей — и ваш профиль готов.' : 'Войдите с email и паролем.'}</p>
    {view !== 'profile' && <div className="account-switch" aria-label="Действие с аккаунтом">
      <button type="button" aria-pressed={view === 'login'} disabled={pending} onClick={() => changeView('login')}>Вход</button>
      <button type="button" aria-pressed={view === 'register'} disabled={pending} onClick={() => changeView('register')}>Регистрация</button>
    </div>}
    <form ref={formRef} noValidate onSubmit={submit} aria-busy={pending}>
      <fieldset disabled={pending} className="account-fields">
        {view !== 'login' && <div className="field"><label htmlFor="account-name">Имя</label>
          <input {...fieldProps('name')} autoComplete="name" maxLength={80} placeholder="Как к вам обращаться"/>{showFieldError('name')}
        </div>}
        <div className="field"><label htmlFor="account-email">Email</label>
          <input {...fieldProps('email')} type="email" autoComplete="username" inputMode="email" maxLength={254} readOnly={view === 'profile'} spellCheck={false} autoCapitalize="none" placeholder="name@example.com"/>{showFieldError('email')}
        </div>
        {view !== 'profile' && <div className="field"><label htmlFor="account-password">Пароль</label>
          <div className="account-password"><input {...fieldProps('password')} type={passwordVisible ? 'text' : 'password'} autoComplete={view === 'register' ? 'new-password' : 'current-password'} maxLength={256}/>
            <button type="button" aria-label={passwordVisible ? 'Скрыть пароль' : 'Показать пароль'} aria-pressed={passwordVisible} onClick={() => setPasswordVisible(value => !value)}>
              {passwordVisible ? <EyeOff size={18} aria-hidden="true"/> : <Eye size={18} aria-hidden="true"/>}
            </button>
          </div>
          {showFieldError('password')}
          {view === 'register' && <p className="account-field-hint" id="account-password-hint">От 15 до 128 символов. Можно использовать фразу с пробелами.</p>}
        </div>}
        {view !== 'login' && <div className="field"><label htmlFor="account-city">Город <span className="account-optional">необязательно</span></label>
          <input {...fieldProps('city')} autoComplete="address-level2" maxLength={80} placeholder="Например, Алматы"/>{showFieldError('city')}
        </div>}
      </fieldset>
      {error && <p className="account-error" role="alert">{error}</p>}
      {success && <p className="account-success" role="status"><Check size={17} aria-hidden="true"/>{success}</p>}
      <Button type="submit" className="account-submit" disabled={pending}>{pending ? 'Подождите…' : view === 'profile' ? 'Сохранить изменения' : view === 'register' ? 'Создать аккаунт' : 'Войти'}</Button>
    </form>
    {view === 'profile'
      ? <div className="account-footer"><Button type="button" variant="ghost" className="account-logout" disabled={pending} onClick={() => void logout()}><LogOut size={17} aria-hidden="true"/>Выйти из аккаунта</Button></div>
      : <p className="account-guest-note">Подбирать подрядчиков можно и без аккаунта.</p>}
  </dialog>
}

export function Account() {
  const [session, setSession] = useState<AccountSession>(emptySession)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const triggerRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const controller = new AbortController()
    void getAccountSession(controller.signal).then(next => {
      if (!controller.signal.aborted) setSession(next)
    }).catch(caught => {
      if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : 'Не удалось проверить вход.')
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false)
    })
    return () => controller.abort()
  }, [])

  useEffect(() => {
    if (!message) return
    const timer = window.setTimeout(() => setMessage(''), 5_000)
    return () => window.clearTimeout(timer)
  }, [message])

  function close(message = '') {
    setOpen(false)
    setMessage(message)
    requestAnimationFrame(() => triggerRef.current?.focus())
  }

  return <>
    <Button ref={triggerRef} variant={session.user ? 'outline' : 'default'} size="sm" type="button" className="account-trigger" disabled={loading}
      aria-haspopup="dialog" aria-label={session.user ? `Профиль: ${session.user.name}` : 'Войти в аккаунт'} onClick={() => { setOpen(true); setMessage('') }}>
      <UserRound size={17} aria-hidden="true"/><span>{loading ? 'Вход…' : session.user ? 'Профиль' : 'Войти'}</span>
    </Button>
    {open && <AccountDialog session={session} initialError={error} onSession={next => { setSession(next); setError('') }} onClose={close}/>}
    <div className={message ? 'account-toast' : 'sr-only'} role="status">{message}</div>
  </>
}
