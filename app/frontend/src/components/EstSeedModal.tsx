import { useEffect, useMemo } from 'react'
import type { Competitor, SideSwap } from './BracketUtils'
import { t, type translationKeys } from '../translate'

interface EstSeedModalProps {
  competitors: Competitor[]
  selectedCategory: string | null
  sideSwaps: SideSwap[]
  sideSwapBailout: string | null
  onClose: () => void
}

type ColumnType = 'number' | 'bool' | 'year'

interface ColumnSpec {
  key: keyof Competitor
  label: string
  type: ColumnType
}

// Frontend-only mirror of the python sort-criteria mapping in
// app/seeding.py:add_estimated_seeds. The crc32 tie-break is intentionally
// excluded.
function columnsForDivision(selectedCategory: string | null): ColumnSpec[] {
  if (!selectedCategory) return []
  const parts = selectedCategory.split(' / ')
  const belt = parts[0] ?? ''
  const age = parts[1] ?? ''
  const weight = parts[3] ?? ''

  const isOpen = /Open/i.test(weight)
  const isBlack = belt === 'BLACK' || belt === 'PRETA'
  const isAdult = age === 'Adult' || age === 'Adulto'
  const isAdultBlack = isAdult && isBlack
  const masterMatch = /^Master (\d+)$/.exec(age)
  const masterLevel = masterMatch ? parseInt(masterMatch[1], 10) : null
  const isMasterBlack = masterLevel !== null && isBlack

  const num = (key: keyof Competitor, label: string): ColumnSpec => ({ key, label, type: 'number' })
  const bool = (key: keyof Competitor, label: string): ColumnSpec => ({ key, label, type: 'bool' })
  const year = (key: keyof Competitor, label: string): ColumnSpec => ({ key, label, type: 'year' })

  if (isAdultBlack && isOpen) {
    return [
      bool('world_champion_recent', t('WC (Last 3)')),
      year('last_world_title_year', t('Last Title')),
      num('grand_slam_open_class_points', t('GS Open Pts')),
      num('grand_slam_points', t('GS Pts')),
      bool('world_champion_4_years_ago', t('WC 4y Ago')),
      bool('world_champion_5_years_ago', t('WC 5y Ago')),
      bool('previous_brown_world_champion', t('Brown WC')),
      bool('former_world_champion', t('Former WC')),
      num('open_class_points', t('Open Pts')),
      num('points', t('Pts')),
    ]
  }
  if (isAdultBlack) {
    return [
      bool('world_champion_recent', t('WC (Last 3)')),
      year('last_world_title_year', t('Last Title')),
      num('grand_slam_points', t('GS Pts')),
      bool('world_champion_4_years_ago', t('WC 4y Ago')),
      bool('world_champion_5_years_ago', t('WC 5y Ago')),
      bool('previous_brown_world_champion', t('Brown WC')),
      bool('former_world_champion', t('Former WC')),
      num('points', t('Pts')),
    ]
  }
  if (isMasterBlack) {
    const masters: ColumnSpec[] = []
    for (let i = 1; i <= (masterLevel as number); i++) {
      masters.push(bool(`master_${i}_world_champion` as keyof Competitor, t(`M${i} WC` as translationKeys)))
    }
    if (isOpen) {
      return [
        bool('adult_world_champion', t('Adult WC')),
        ...masters,
        num('grand_slam_open_class_points', t('GS Open Pts')),
        num('grand_slam_points', t('GS Pts')),
        num('open_class_points', t('Open Pts')),
        num('points', t('Pts')),
      ]
    }
    return [
      bool('adult_world_champion', t('Adult WC')),
      ...masters,
      num('grand_slam_points', t('GS Pts')),
      num('points', t('Pts')),
    ]
  }
  if (isOpen) {
    return [
      num('grand_slam_open_class_points', t('GS Open Pts')),
      num('grand_slam_points', t('GS Pts')),
      num('open_class_points', t('Open Pts')),
      num('points', t('Pts')),
    ]
  }
  return [
    num('grand_slam_points', t('GS Pts')),
    num('points', t('Pts')),
  ]
}

function renderCell(value: unknown, type: ColumnType): string {
  if (type === 'bool') return value ? '✓' : ''
  if (type === 'year') return value == null ? '' : String(value)
  if (value == null) return ''
  return String(value)
}

function EstSeedModal({ competitors, selectedCategory, sideSwaps, sideSwapBailout, onClose }: EstSeedModalProps) {
  const columns = useMemo(() => columnsForDivision(selectedCategory), [selectedCategory])

  const sorted = useMemo(() => {
    return [...competitors].sort((a, b) => {
      const aSeed = a.est_seed ?? Number.MAX_SAFE_INTEGER
      const bSeed = b.est_seed ?? Number.MAX_SAFE_INTEGER
      return aSeed - bSeed
    })
  }, [competitors])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal is-active est-seed-modal">
      <div className="modal-background" onClick={onClose}></div>
      <div className="modal-content est-seed-modal-content">
        <button
          className="delete is-medium est-seed-modal-close"
          aria-label="close"
          onClick={onClose}
        ></button>
        <div className="est-seed-modal-body">
          <h2 className="title is-5">{t('Estimated Seeding')}</h2>
          <div className="table-container">
            <table className="table is-fullwidth est-seed-modal-table">
              <thead>
                <tr>
                  <th>{t('Name')}</th>
                  <th>{t('Team')}</th>
                  {columns.map(c => (
                    <th
                      key={c.key as string}
                      className={`no-wrap ${c.type === 'bool' ? 'has-text-centered' : 'has-text-right'}`}
                    >
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map(c => (
                  <tr key={`${c.name}-${c.est_seed ?? ''}`}>
                    <td>{c.personal_name ? c.personal_name : c.name}</td>
                    <td>{c.team}</td>
                    {columns.map(col => (
                      <td
                        key={col.key as string}
                        className={col.type === 'bool' ? 'has-text-centered' : 'has-text-right'}
                      >
                        {renderCell(c[col.key], col.type)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {sideSwapBailout && (
            <div className="notification is-warning is-light est-seed-swap-note mt-4">
              {sideSwapBailout}
            </div>
          )}
          {sideSwaps.length > 0 && (
            <div className="notification is-info is-light est-seed-swap-note mt-4">
              <p className="mb-2"><strong>{t('Same-team side-swaps applied')}:</strong></p>
              <ul>
                {sideSwaps.map((s, i) => (
                  <li key={i}>{s.name_a} ↔ {s.name_b}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="est-seed-disclaimer mt-4">
            {t('Estimated seeding is a BETA feature and can vary from the actual seeding for a division for many reasons, including but not limited to: missing medals in our system, athletes changing teams or gaining points before an event, and differences in tie breaks. These seeds should not be mistaken for official IBJJF seeds.')}
          </p>
        </div>
      </div>
    </div>
  )
}

export default EstSeedModal
