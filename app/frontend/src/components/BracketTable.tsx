import { noMatchStrings, immatureClass, badgeForPercentile } from '../utils'
import classNames from 'classnames';
import dayjs from 'dayjs'
import { useAppContext } from '../AppContext'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Competitor, MatLinks } from './BracketUtils'
import { Tooltip } from 'react-tooltip';
import { t } from '../translate'
import NameInfo from './NameInfo'
import youtubeLogo from '/src/assets/youtube.png'

interface BracketTableProps {
  competitors: Competitor[] | null;
  matLinks?: MatLinks | null;
  selectedCategory: string | null;
  sortColumn?: string;
  showSeed: boolean;
  showWeight?: boolean;
  showRank?: boolean;
  showEndRating?: boolean;
  showNext?: boolean;
  showRatings: boolean;
  isGi: boolean;
  belt: string;
  columnClicked?: (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => void;
  athleteClicked: (ev: React.MouseEvent<HTMLAnchorElement>, slug: string) => void;
  calculateEnabled: (athlete: Competitor) => boolean;
}

export type SortColumn = 'rating' | 'seed' | 'next'

function BracketTable(props: BracketTableProps) {
  const {
    competitors,
    sortColumn,
    columnClicked,
    athleteClicked,
    isGi,
    selectedCategory,
    belt,
  } = props;

  const {
    setCalcFirstAthlete,
    setCalcSecondAthlete,
    setCalcGender,
    setCalcAge,
    setCalcBelt,
    setCalcFirstWeight,
    setCalcSecondWeight,
    setCalcCustomInfo,
    setActiveTab,
  } = useAppContext()

  const navigate = useNavigate()

  const [selectedAthletes, setSelectedAthletes] = useState<Competitor[]>([]);

  useEffect(() => {
    setSelectedAthletes([]);
  }, [competitors]);

  const handleCheckboxChange = (competitor: Competitor) => {
    setSelectedAthletes(prev => {
      if (prev.includes(competitor)) {
        return prev.filter(c => c !== competitor);
      } else {
        return [...prev, competitor];
      }
    });
  };

  const calculateMatchResult = () => {
    if (!competitors) {
      return;
    }
    const sortedSelectedAtheletes = competitors.filter(c => selectedAthletes.includes(c));
    const firstAthlete = sortedSelectedAtheletes[0];
    const secondAthlete = sortedSelectedAtheletes[1];

    if (firstAthlete && secondAthlete && selectedCategory) {
      const [belt, age, gender, weight] = selectedCategory.split(' / ');
      setCalcFirstAthlete(firstAthlete.name);
      setCalcSecondAthlete(secondAthlete.name);
      setCalcGender(gender);
      setActiveTab(isGi ? 'Gi' : 'No Gi');
      if (!/Open/i.test(weight)) {
        setCalcFirstWeight(weight);
        setCalcSecondWeight(weight);
        setCalcAge(age);
        setCalcBelt(belt);
        setCalcCustomInfo(true);
      } else {
        setCalcCustomInfo(false);
      }

      navigate('/calculator');
    }
  };

  const competitorTooltip = (competitor: Competitor) => {
    let tooltip = ''

    if (competitor.rating !== null && competitor.note) {
      tooltip = competitor.note
    }

    const immature = immatureClass(competitor.match_count);
    if (immature !== '') {
      if (tooltip) {
        tooltip += ', '
      }
      if (immature === 'very-immature') {
        tooltip += `${t("Athlete's rating is provisional due to insufficient matches within three years")} (${competitor.match_count})`
      } else {
        tooltip += `${t("Athlete's rating is semi-provisional due to insufficient matches within three years")} (${competitor.match_count})`
      }
    }

    if (tooltip) {
      return tooltip;
    }
    return undefined
  }

  const changeClass = (start: number | null, end: number | null) => {
    if (start === null || end === null || start === end) {
      return 'has-text-right';
    }

    let diff = end - start;

    if (diff > 0) {
      return 'has-text-right has-text-success';
    } else {
      return 'has-text-right has-text-danger';
    }
  }

  const calculateDisabled = () => {
    return selectedAthletes.length !== 2 || selectedAthletes.filter(a => props.calculateEnabled(a)).length !== 2
  };

  const getMatLink = (where: string, when: string, matLinks: MatLinks | null | undefined): string | null => {
    if (!matLinks) {
      return null;
    }

    const dateIso = dayjs(when).format('YYYY-MM-DD');
    const matLinkEntry = matLinks[dateIso];
    if (!matLinkEntry) {
      return null;
    }

    const whereParts = where.split(/\s+/);
    const matNumberString = whereParts[whereParts.length - 1];

    return matLinkEntry[matNumberString] ?? null; 
  }

  return (
    <div className="table-container">
      {
        props.showWeight &&
        <div className="notification mt-5">
          {t("Our open class seeding uses a combination of weight and skill")}
        </div>
      }
      <table className="table is-fullwidth bracket-table">
        <thead>
          <tr>
            {
              props.showRatings &&
              <th></th>
            }
            {
              props.showRatings &&
              <th className="has-text-right">
                {
                  (sortColumn !== undefined && sortColumn !== 'rating') ?
                    <a href="#" onClick={columnClicked?.bind(null, 'rating')}>#</a> :
                    <span># ↓</span>
                }
              </th>
            }
            {
              props.showSeed &&
              <th className="has-text-right">
                {
                  (sortColumn !== undefined && sortColumn !== 'seed') ?
                    <a href="#" onClick={columnClicked?.bind(null, 'seed')}>{t("IBJJF Seed")}</a> :
                    <span>{t("IBJJF Seed")} ↓</span>
                }
              </th>
            }
            <th></th>
            <th>{t("Name")}</th>
            <th className="is-visible-mobile-table-cell cell-no-padding"></th>
            <th>{t("Team")}</th>
            {
              props.showWeight &&
              <th>{t("Weight")}</th>
            }
            {
              props.showNext &&
              <th>
              {
                (sortColumn !== undefined && sortColumn !== 'next') ?
                  <a href="#" onClick={columnClicked?.bind(null, 'next')}>{t("Next")}</a> :
                  <span>{t("Next")} ↓</span>
              }
              </th>
            }
            {
             props.showRatings &&
              <>
                <th className="has-text-right">
                {
                  props.showEndRating ? t('Start Rating') : t('Rating')
                }
                </th>
              </>
            }
            <th></th>
            {
              (props.showRatings && props.showEndRating) &&
              <th className="has-text-right">{t('End Rating')}</th>
            }
            {
              (props.showRatings && props.showRank) &&
              <th className="has-text-right">{t('Rank')}</th>
            }
          </tr>
        </thead>
        <tbody>
          {
            competitors?.map(competitor => {
              const [badge, badgeDesc] = badgeForPercentile(competitor.percentile, belt);
              return (
              <tr key={competitor.name}>
                {
                  props.showRatings &&
                  <td>
                    <input
                      className="has-cursor-pointer"
                      type="checkbox"
                      disabled={competitor.rating === null}
                      checked={selectedAthletes.includes(competitor)}
                      onChange={() => handleCheckboxChange(competitor)}
                    />
                  </td>
                }
                { props.showRatings &&
                <td className="has-text-right">{competitor.ordinal}</td>
                }
                {
                  props.showSeed &&
                  <td className="has-text-right">{competitor.seed}</td>
                }
                {
                  <td className="badge-table-cell">
                    {
                      badge &&
                      <figure className="image is-24x24 athlete-elite-badge" data-tooltip-id="badge-tooltip" data-tooltip-content={badgeDesc} data-tooltip-place="top">
                        <img src={badge} alt={badgeDesc} />
                      </figure>
                    }
                  </td>
                }
                {
                  competitor.id !== null ?
                    <>
                      <td className={classNames({"strike-through": noMatchStrings.some(s => competitor.note?.toLowerCase() === s)})}>
                        <div className="name-container">
                          <a href="#" onClick={e => athleteClicked(e, competitor.slug)}>{competitor.personal_name ? competitor.personal_name : competitor.name}</a>
                          <div className="is-hidden-mobile">
                            <NameInfo instagram_profile={competitor.instagram_profile}
                                      profile_image_url={competitor.profile_image_url}
                                      country={competitor.country} country_note={competitor.country_note} country_note_pt={competitor.country_note_pt}
                                      medal={competitor.medal} />
                          </div>
                        </div>
                      </td>
                      <td className="is-visible-mobile-table-cell cell-no-side-padding">
                        <NameInfo instagram_profile={competitor.instagram_profile}
                                  profile_image_url={competitor.profile_image_url}
                                  country={competitor.country} country_note={competitor.country_note} country_note_pt={competitor.country_note_pt}
                                  medal={competitor.medal} />
                      </td>
                    </> :
                    <>
                      <td className={classNames({"strike-through": noMatchStrings.some(s => competitor.note?.toLowerCase() === s)})}>
                        <div className="name-container">
                          <span>
                            {competitor.personal_name ? competitor.personal_name : competitor.name}
                          </span>
                          <div className="is-hidden-mobile">
                            <NameInfo instagram_profile={null} profile_image_url={null} country={null} country_note={null} country_note_pt={null} medal={competitor.medal} />
                          </div>
                        </div>
                      </td>
                      <td className="is-visible-mobile-table-cell cell-no-side-padding">
                        <NameInfo instagram_profile={null} profile_image_url={null} country={null} country_note={null} country_note_pt={null} medal={competitor.medal} />
                      </td>
                    </>
                }
                <td>{competitor.team}</td>
                {
                  props.showWeight &&
                  <td>{competitor.last_weight}</td>
                }
              {
                  props.showNext &&
                  <td>
                    <div className="next-match-div">
                      {
                        (competitor.next_where && competitor.next_when) &&
                        <span>{competitor.next_where} - {dayjs(competitor.next_when).format('ddd h:mma')}</span>
                      }
                      {
                      (competitor.next_where && competitor.next_when && getMatLink(competitor.next_where, competitor.next_when, props.matLinks)) &&
                        <a href={getMatLink(competitor.next_where, competitor.next_when, props.matLinks) ?? ''} target="_blank" rel="noopener noreferrer">
                          <img src={youtubeLogo} alt="Mat Link" style={{width: '20px', height: '20px'}} />
                        </a>
                      }
                    </div>
                  </td>
                }
                {
                  props.showRatings &&
                  <>
                    <td className="has-text-right">
                      <span className={immatureClass(competitor.match_count)}>{competitor.rating !== null ? Math.round(competitor.rating) : ''}</span>
                    </td>
                    <td className={classNames("has-text-centered", {"has-cursor-pointer": competitorTooltip(competitor)})} data-tooltip-place="left" data-tooltip-id="competitor-tooltip" data-tooltip-content={competitorTooltip(competitor)}>
                      {
                        immatureClass(competitor.match_count) === 'very-immature' ?
                          <span className="very-immature-bullet">&nbsp;</span> : (
                            immatureClass(competitor.match_count) === 'immature' ?
                              <span className="immature-bullet">&nbsp;</span> : (
                              competitorTooltip(competitor) && <span className="plain-bullet">&nbsp;</span>
                            )
                          )
                      }
                    </td>
                  </>
                }
                {
                  (props.showRatings && props.showEndRating) &&
                  <td className={changeClass(competitor.rating, competitor.end_rating)}>
                    <span className={immatureClass(competitor.end_match_count)}>{competitor.end_rating !== null ? Math.round(competitor.end_rating) : ''}</span>
                  </td>
                }
                {
                  (props.showRatings && props.showRank) &&
                  <td className="has-text-right">{immatureClass(competitor.match_count) !== 'very-immature' && (competitor.rank ?? '')}</td>
                }
              </tr>
            )})
          }
        </tbody>
      </table>
      {
        props.showRatings &&
        <button
          className="button is-info mt-2"
          onClick={calculateMatchResult}
          disabled={calculateDisabled()}>
          {t("Calculate Expected Match Result")}
        </button>
      }
      <Tooltip id="badge-tooltip" className="tooltip-normal" />
      <Tooltip id="competitor-tooltip" className="tooltip-multiline" />
    </div>
  );
}

export default BracketTable;