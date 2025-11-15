import { badgeForPercentile } from '../utils'
import { t } from '../translate'
import { Tooltip } from 'react-tooltip'
import NameInfo from "./NameInfo";

export interface EliteAthlete {
  name: string
  team: string
  id: string | number | null
  slug: string | null
  rating: number | null
  match_count: number | null
  rank: number | null
  percentile: number | null
  tier: number
  category: string
  belt: string
  age: string
  gender: string
  weight: string
  gi: boolean
  personal_name: string | null
  instagram_profile: string | null
  profile_image_url: string | null
  country: string | null
  country_note: string | null
  country_note_pt: string | null
}

interface EliteTableProps {
  elites: EliteAthlete[] | null
  isGi: boolean
  athleteClicked: (ev: React.MouseEvent<HTMLAnchorElement>, slug: string) => void
}

function EliteTable(props: EliteTableProps) {
  const { elites, athleteClicked } = props

  return (
    <div className="table-container">
      <table className="table is-fullwidth bracket-table">
        <thead>
          <tr>
            <th></th>
            <th>{t('Name')}</th>
            <th className="is-visible-mobile-table-cell cell-no-padding"></th>
            <th>{t('Team')}</th>
            <th>{t('Category')}</th>
            <th className="has-text-right">{t('Rating')}</th>
            <th className="has-text-right">{t('Rank')}</th>
          </tr>
        </thead>
        <tbody>
        {
          elites?.map(e => {
            const [badge, badgeDesc] = badgeForPercentile(e.percentile, e.belt)
            return (
              <tr key={`${e.name}-${e.team}-${e.category}`}>
                <td className="badge-table-cell">
                  {badge &&
                    <figure className="image is-24x24 athlete-elite-badge" data-tooltip-id="badge-tooltip" data-tooltip-content={badgeDesc} data-tooltip-place="top">
                      <img src={badge} alt={badgeDesc} />
                    </figure>
                  }
                </td>
                <td>
                  <div className="name-container">
                    {e.slug ? (
                      <a href="#" onClick={(ev) => athleteClicked(ev, e.slug!)}>{e.name}</a>
                    ) : (
                      <span>{e.name}</span>
                    )}
                    <div className="is-hidden-mobile">
                      <NameInfo instagram_profile={e.instagram_profile}
                                profile_image_url={e.profile_image_url}
                                country={e.country} country_note={e.country_note} country_note_pt={e.country_note_pt} />
                    </div>
                  </div>
                </td>
                <td className="is-visible-mobile-table-cell cell-no-side-padding">
                  <NameInfo instagram_profile={e.instagram_profile}
                            profile_image_url={e.profile_image_url}
                            country={e.country} country_note={e.country_note} country_note_pt={e.country_note_pt} />
                </td>
                <td>{e.team}</td>
                <td>{e.category}</td>
                <td className="has-text-right">{e.rating !== null ? Math.round(e.rating) : ''}</td>
                <td className="has-text-right">{e.rank ?? ''}</td>
              </tr>
            )
          })
        }
        </tbody>
      </table>
      <Tooltip id="badge-tooltip" className="tooltip-normal" />
    </div>
  )
}

export default EliteTable
