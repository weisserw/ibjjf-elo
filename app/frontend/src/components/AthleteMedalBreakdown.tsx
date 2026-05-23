import { useEffect, useMemo, useState } from 'react'
import axios from 'axios'
import {
  handleError,
  type AthleteMedalDetail,
  type MedalBreakdownBucket,
  type MedalBreakdownResponse,
} from './BracketUtils'
import { t } from '../translate'

interface AthleteMedalBreakdownProps {
  athleteId: string
  link: string
  division: string
  gi: boolean
}

type TabKey = 'points' | 'grand_slam'

function formatWeightMult(weightMult: number): string {
  const pct = weightMult * 100
  const rounded = Math.round(pct * 100) / 100
  return `${rounded}%`
}

function formatNumber(value: number): string {
  if (Number.isInteger(value)) return String(value)
  return String(Math.round(value * 100) / 100)
}

function medalEmoji(place: number): string {
  if (place === 1) return '🥇'
  if (place === 2) return '🥈'
  if (place === 3) return '🥉'
  return ''
}

const emptyBucket: MedalBreakdownBucket = {
  medals: [],
  points_total: 0,
  open_class_points_total: 0,
}

function BreakdownTable({ medals, pointsTotal, openClassTotal, divisionIsOpen, emptyMessage }: {
  medals: AthleteMedalDetail[]
  pointsTotal: number
  openClassTotal: number
  divisionIsOpen: boolean
  emptyMessage: string
}) {
  if (medals.length === 0) {
    return <p className="mt-4">{emptyMessage}</p>
  }
  return (
    <div className="table-container">
      <table className="table is-fullwidth est-seed-modal-table">
        <thead>
          <tr>
            <th className="medal-emoji-cell"></th>
            <th>{t('Event')}</th>
            <th>{t('Division')}</th>
            <th className="has-text-right">{t('Points')}</th>
            <th className="has-text-right">{t('Star')}</th>
            <th className="has-text-right">{t('Season')}</th>
            <th className="has-text-right">{t('Weight')}</th>
            <th className="has-text-right">{t('Total')}</th>
          </tr>
        </thead>
        <tbody>
          {medals.map((m, i) => (
            <tr key={`${m.event_name}-${m.happened_at ?? ''}-${i}`}>
              <td className="medal-emoji-cell">{medalEmoji(m.place)}</td>
              <td>{m.event_name}</td>
              <td>{m.division_weight}</td>
              <td className="has-text-right">{formatNumber(m.base_points)}</td>
              <td className="has-text-right">x {formatNumber(m.star)}</td>
              <td className="has-text-right">x {formatNumber(m.season_mult)}</td>
              <td className="has-text-right">{formatWeightMult(m.weight_mult)}</td>
              <td className="has-text-right">{formatNumber(m.total)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          {divisionIsOpen ? (
            <>
              <tr>
                <th colSpan={7} className="has-text-right">{t('Open Class Total')}</th>
                <th className="has-text-right">{openClassTotal}</th>
              </tr>
              <tr>
                <th colSpan={7} className="has-text-right">{t('Point Total')}</th>
                <th className="has-text-right">{pointsTotal}</th>
              </tr>
            </>
          ) : (
            <tr>
              <th colSpan={7} className="has-text-right">{t('Total')}</th>
              <th className="has-text-right">{pointsTotal}</th>
            </tr>
          )}
        </tfoot>
      </table>
    </div>
  )
}

function AthleteMedalBreakdown({ athleteId, link, division, gi }: AthleteMedalBreakdownProps) {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [points, setPoints] = useState<MedalBreakdownBucket>(emptyBucket)
  const [grandSlam, setGrandSlam] = useState<MedalBreakdownBucket>(emptyBucket)
  const [activeTab, setActiveTab] = useState<TabKey>('grand_slam')

  useEffect(() => {
    let cancelled = false
    const fetchData = async () => {
      setLoading(true)
      setError(null)
      try {
        const { data } = await axios.get<MedalBreakdownResponse>(
          '/api/brackets/registrations/competitor_medal_breakdown',
          { params: { link, division, gi, athlete_id: athleteId } }
        )
        if (cancelled) return
        if (data.error) {
          setError(data.error)
          setPoints(emptyBucket)
          setGrandSlam(emptyBucket)
        } else {
          setPoints(data.points ?? emptyBucket)
          setGrandSlam(data.grand_slam ?? emptyBucket)
        }
      } catch (err) {
        if (!cancelled) handleError(err, setError)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchData()
    return () => {
      cancelled = true
    }
  }, [athleteId, link, division, gi])

  const divisionIsOpen = useMemo(() => {
    const parts = division.split(' / ')
    const weight = parts[3] ?? ''
    return /Open/i.test(weight)
  }, [division])

  const showGrandSlamTab = useMemo(
    () =>
      grandSlam.medals.length > 0 ||
      grandSlam.points_total > 0 ||
      grandSlam.open_class_points_total > 0,
    [grandSlam]
  )

  useEffect(() => {
    if (loading) return
    if (!showGrandSlamTab && activeTab === 'grand_slam') {
      setActiveTab('points')
    }
  }, [loading, showGrandSlamTab, activeTab])

  if (loading) {
    return <div className="bracket-loader loader mt-4"></div>
  }

  if (error) {
    return (
      <div className="notification is-danger is-light mt-4">
        {error}
      </div>
    )
  }

  return (
    <>
      {showGrandSlamTab && (
        <div className="tabs is-boxed mb-3 medal-breakdown-tabs">
          <ul>
            <li className={activeTab === 'grand_slam' ? 'is-active' : ''}>
              <a onClick={() => setActiveTab('grand_slam')}>{t('Grand Slam')}</a>
            </li>
            <li className={activeTab === 'points' ? 'is-active' : ''}>
              <a onClick={() => setActiveTab('points')}>{t('Points')}</a>
            </li>
          </ul>
        </div>
      )}
      {activeTab === 'points' ? (
        <BreakdownTable
          medals={points.medals}
          pointsTotal={points.points_total}
          openClassTotal={points.open_class_points_total}
          divisionIsOpen={divisionIsOpen}
          emptyMessage={t("No medals contribute to this athlete's regular-season points for this division.")}
        />
      ) : (
        <BreakdownTable
          medals={grandSlam.medals}
          pointsTotal={grandSlam.points_total}
          openClassTotal={grandSlam.open_class_points_total}
          divisionIsOpen={divisionIsOpen}
          emptyMessage={t("No medals contribute to this athlete's grand slam points for this division.")}
        />
      )}
    </>
  )
}

export default AthleteMedalBreakdown
