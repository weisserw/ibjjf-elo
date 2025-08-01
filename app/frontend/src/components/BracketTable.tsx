import { immatureClass } from "../utils"
import classNames from 'classnames';
import dayjs from 'dayjs'
import { useAppContext } from '../AppContext'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { noMatchStrings, type Competitor } from "./BracketUtils"
import { Tooltip } from 'react-tooltip';

interface BracketTableProps {
  competitors: Competitor[] | null;
  selectedCategory: string | null;
  sortColumn?: string;
  showSeed: boolean;
  showWeight?: boolean;
  showRank?: boolean;
  showEndRating?: boolean;
  showNext?: boolean;
  showRatings: boolean;
  isGi: boolean;
  columnClicked?: (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => void;
  athleteClicked: (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => void;
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
        tooltip += `Athlete's rating is provisional due to insufficient matches (${competitor.match_count})`
      } else {
        tooltip += `Athlete's rating is semi-provisional due to insufficient matches (${competitor.match_count})`
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

  const competitorMedal = (medal: string | undefined) => {
    if (medal === undefined) {
      return null;
    }
    if (medal === '1') {
      return <span> 🥇</span>;
    } else if (medal === '2') {
      return <span> 🥈</span>;
    } else if (medal === '3') {
      return <span> 🥉</span> 
    } else {
      return null;
    }
  }

  const calculateDisabled = () => {
    return selectedAthletes.length !== 2 || selectedAthletes.filter(a => props.calculateEnabled(a)).length !== 2
  };

  return (
    <div className="table-container">
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
                    <a href="#" onClick={columnClicked?.bind(null, 'seed')}>IBJJF Seed</a> :
                    <span>IBJJF Seed ↓</span>
                }
              </th>
            }
            <th>Name</th>
            <th>Team</th>
            {
              props.showWeight &&
              <th>Weight</th>
            }
            {
              props.showNext &&
              <th>
              {
                (sortColumn !== undefined && sortColumn !== 'next') ?
                  <a href="#" onClick={columnClicked?.bind(null, 'next')}>Next</a> :
                  <span>Next ↓</span>
              }
              </th>
            }
            {
             props.showRatings &&
              <>
                <th className="has-text-right">
                {
                  props.showEndRating ? 'Start Rating' : 'Rating'
                }
                </th>
              </>
            }
            <th></th>
            {
              (props.showRatings && props.showEndRating) &&
              <th className="has-text-right">End Rating</th>
            }
            {
              (props.showRatings && props.showRank) &&
              <th className="has-text-right">Rank</th>
            }
          </tr>
        </thead>
        <tbody>
          {
            competitors?.map(competitor => (
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
                  competitor.id !== null ?
                    <td className={classNames({"strike-through": noMatchStrings.some(s => competitor.note?.toLowerCase() === s)})}><a href="#" onClick={e => athleteClicked(e, competitor.name)}>{competitor.name}{competitorMedal(competitor.medal)}</a></td> :
                    <td className={classNames({"strike-through": noMatchStrings.some(s => competitor.note?.toLowerCase() === s)})}>{competitor.name}{competitorMedal(competitor.medal)}</td>
                }
                <td>{competitor.team}</td>
                {
                  props.showWeight &&
                  <td>{competitor.last_weight}</td>
                }
              {
                  props.showNext &&
                  <td>{competitor.next_where && competitor.next_when && `${competitor.next_where} - ${dayjs(competitor.next_when).format('ddd h:mma')}`}</td>
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
            ))
          }
        </tbody>
      </table>
      {
        props.showRatings &&
        <button
          className="button is-info mt-2"
          onClick={calculateMatchResult}
          disabled={calculateDisabled()}>
          Calculate Expected Match Result
        </button>
      }
      <Tooltip id="competitor-tooltip" className="tooltip-multiline" />
    </div>
  );
}

export default BracketTable;