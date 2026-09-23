import { CalendarDays, ChevronDown, Clock3, MapPin } from 'lucide-react'
import type { RecommendationCard as RecommendationCardData } from '../lib/api/generated'

type RecommendationCardProps = {
  card: RecommendationCardData
  index: number
}

const tones = ['blue', 'purple', 'sand'] as const

export function RecommendationCard({ card, index }: RecommendationCardProps) {
  const initials = card.anon_name.trim().split(/\s+/).slice(0, 2).map(part => Array.from(part)[0]).join('').toLocaleUpperCase('ru')
  const titleId = `profile-${card.id}`

  return (
    <article className="contractor-card" data-profile-id={card.id} aria-labelledby={titleId}>
      <div className="card-top">
        <div className={`avatar ${tones[index % tones.length]}`} aria-hidden="true">{initials}</div>
        <div className="identity">
          <span className="card-category">{card.category} <span>/ {String(index + 1).padStart(2, '0')}</span></span>
          <h3 id={titleId}>{card.anon_name}</h3>
          <span className="city"><MapPin size={13} aria-hidden="true" />{card.city}</span>
          <span className="profile-id">{card.id}</span>
        </div>
        <div className="price">{card.price_label}<small>за мероприятие</small></div>
      </div>

      <div className="card-attributes">
        <span><CalendarDays size={14} aria-hidden="true" />{card.availability_text}</span>
        <span>{card.languages.length ? `Языки: ${card.languages.join(', ')}` : 'Языки не указаны в профиле'}</span>
        <span><Clock3 size={14} aria-hidden="true" />{card.duration_text}</span>
      </div>

      <div className="explanation">
        <span className="explanation-label">Почему подходит</span>
        <p>{card.explanation}</p>
      </div>

      {card.warnings.length > 0 && (
        <ul className="card-warnings" aria-label="Ограничения сведений о профиле">
          {card.warnings.map((warning, warningIndex) => (
            <li key={`${warning.code}-${warningIndex}`}>{warning.message}</li>
          ))}
        </ul>
      )}

      <div className="card-bottom">
        <div className="profile-labels" aria-label="Источник сведений">
          {card.origin === 'original' && <span className="synthetic">Исходный каталог</span>}
          {card.labels.map(label => <span className="synthetic" key={label}>{label}</span>)}
        </div>
        <details>
          <summary>Основания <ChevronDown size={14} aria-hidden="true" /></summary>
          <div className="evidence">
            {card.evidence.map((evidence, evidenceIndex) => (
              <p key={`${evidence.code}-${evidenceIndex}`}>{evidence.text}</p>
            ))}
          </div>
        </details>
      </div>
    </article>
  )
}
