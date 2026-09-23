import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, RotateCcw, SlidersHorizontal, X } from 'lucide-react'
import { Button } from './ui/button'

const defaultAccent = '#2563EB'
const storageKey = 'ai-ana-accent'
const presets = [
  ['Синий', '#2563EB'],
  ['Зелёный', '#15803D'],
  ['Фиолетовый', '#7C3AED'],
  ['Оранжевый', '#C2410C'],
] as const

const validHex = (value: string) => /^#[\da-f]{6}$/i.test(value)

function getSavedAccent() {
  try {
    const value = localStorage.getItem(storageKey)
    return value && validHex(value) ? value.toUpperCase() : defaultAccent
  } catch {
    return defaultAccent
  }
}

function onAccent(hex: string) {
  const rgb = [1, 3, 5]
    .map(index => parseInt(hex.slice(index, index + 2), 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
  const luminance = rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722
  return luminance > .179 ? '#000000' : '#FFFFFF'
}

export function AppearanceSettings() {
  const [accent, setAccent] = useState(getSavedAccent)
  const [hex, setHex] = useState(accent)
  const [appearance, setAppearance] = useState(false)
  const [storageAvailable, setStorageAvailable] = useState(true)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  const closeAppearance = useCallback(() => {
    setAppearance(false)
    triggerRef.current?.focus()
  }, [])

  useEffect(() => {
    const root = document.documentElement
    root.style.setProperty('--accent', accent)
    root.style.setProperty('--on-accent', onAccent(accent))
    try {
      localStorage.setItem(storageKey, accent)
      setStorageAvailable(true)
    } catch {
      setStorageAvailable(false)
    }
  }, [accent])

  useEffect(() => {
    if (!appearance) return
    closeRef.current?.focus()
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeAppearance()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [appearance, closeAppearance])

  function selectAccent(value: string) {
    setHex(value)
    if (validHex(value)) setAccent(value.toUpperCase())
  }

  return <>
    <Button
      ref={triggerRef}
      type="button"
      variant="outline"
      size="sm"
      aria-expanded={appearance}
      aria-controls="appearance"
      onClick={() => setAppearance(open => !open)}
    >
      <SlidersHorizontal size={16} aria-hidden="true"/> Оформление
    </Button>
    {appearance && <section className="appearance" id="appearance" aria-label="Настройки оформления">
      <div className="section-line">
        <h2>Ваш акцентный цвет</h2>
        <Button ref={closeRef} type="button" variant="ghost" size="sm" aria-label="Закрыть настройки" onClick={closeAppearance}>
          <X size={18} aria-hidden="true"/>
        </Button>
      </div>
      <p>{storageAvailable
        ? 'Немного вашего стиля. Настройки сохраняются в этом браузере.'
        : 'Сохранение в браузере недоступно. Цвет действует до перезагрузки страницы.'}</p>
      <div className="swatches">
        {presets.map(([name, color]) => <button
          key={name}
          type="button"
          aria-pressed={accent === color}
          onClick={() => selectAccent(color)}
        >
          <span style={{ background: color }} aria-hidden="true"/>{name}
          {accent === color && <Check size={14} aria-hidden="true"/>}
        </button>)}
      </div>
      <label className="hex-label" htmlFor="hex">Свой цвет</label>
      <div className="color-inputs">
        <input type="color" aria-label="Выбрать акцентный цвет" value={accent} onChange={event => selectAccent(event.target.value)}/>
        <input
          id="hex"
          value={hex}
          maxLength={7}
          spellCheck={false}
          autoComplete="off"
          onChange={event => selectAccent(event.target.value)}
          aria-invalid={!validHex(hex)}
          aria-describedby={!validHex(hex) ? 'hex-error' : undefined}
        />
      </div>
      {!validHex(hex) && <p id="hex-error" className="field-error">Введите цвет в формате #RRGGBB.</p>}
      <Button type="button" variant="ghost" size="sm" onClick={() => selectAccent(defaultAccent)}>
        <RotateCcw size={14} aria-hidden="true"/> Вернуть стандартный цвет
      </Button>
    </section>}
  </>
}
