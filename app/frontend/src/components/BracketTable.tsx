import { immatureClass } from "../utils"
import classNames from 'classnames';
import { useAppContext } from '../AppContext'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Competitor } from "./BracketUtils"


interface BracketTableProps {
  competitors: Competitor[] | null;
  sortColumn?: string;
  showSeed: boolean;
  isGi: boolean;
  columnClicked?: (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => void;
  athleteClicked: (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => void;
}

export type SortColumn = 'rating' | 'seed'

function BracketTable(props: BracketTableProps) {
  const {
    competitors,
    sortColumn,
    columnClicked,
    athleteClicked,
    isGi,
  } = props;

  const {
    bracketSelectedCategory,
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

  const handleCheckboxChange = (competitor: Competitor) => {
    setSelectedAthletes(prev => {
      if (prev.includes(competitor)) {
        return prev.filter(c => c !== competitor);
      } else {
        return [...prev, competitor];
      }
    });
  };

  const calculateDisabled = () => {
    return selectedAthletes.length !== 2 || selectedAthletes.filter(a => a.rating !== null).length !== 2
  };

  const calculateMatchResult = () => {
    if (!competitors) {
      return;
    }
    const sortedSelectedAtheletes = competitors.filter(c => selectedAthletes.includes(c));
    const firstAthlete = sortedSelectedAtheletes[0];
    const secondAthlete = sortedSelectedAtheletes[1];

    if (firstAthlete && secondAthlete && bracketSelectedCategory) {
      const [belt, age, gender, weight] = bracketSelectedCategory.split(' / ');
      setCalcFirstAthlete(firstAthlete.name);
      setCalcSecondAthlete(secondAthlete.name);
      setCalcGender(gender);
      setCalcAge(age);
      setCalcBelt(belt);
      if (!/Open/i.test(weight)) {
        setCalcFirstWeight(weight);
        setCalcSecondWeight(weight);
      }
      setActiveTab(isGi ? 'Gi' : 'No Gi');
      setCalcCustomInfo(true);
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
      return tooltip
    }
    return undefined
  }

  return (
    <div className="table-container">
      <table className="table is-fullwidth bracket-table">
        <thead>
          <tr>
            <th></th>
            <th className="has-text-right">
              {
                (sortColumn !== undefined && sortColumn !== 'rating') ?
                  <a href="#" onClick={columnClicked?.bind(null, 'rating')}>#</a> :
                  <span># ↓</span>
              }
            </th>
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
            <th className="has-text-right">Rating</th>
            <th className="has-text-right">Rank</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {
            competitors?.map(competitor => (
              <tr key={competitor.name}>
                <td>
                  <input
                    className="has-cursor-pointer"
                    type="checkbox"
                    disabled={competitor.rating === null}
                    checked={selectedAthletes.includes(competitor)}
                    onChange={() => handleCheckboxChange(competitor)}
                  />
                </td>
                <td className="has-text-right">{competitor.ordinal}</td>
                {
                  props.showSeed &&
                  <td className="has-text-right">{competitor.seed}</td>
                }
                {
                  competitor.id !== null ?
                    <td><a href="#" onClick={e => athleteClicked(e, competitor.name)}>{competitor.name}</a></td> :
                    <td>{competitor.name}</td>
                }
                <td>{competitor.team}</td>
                <td className="has-text-right">
                  <span className={immatureClass(competitor.match_count)}>{competitor.rating ?? ''}</span>
                </td>
                <td className="has-text-right">{immatureClass(competitor.match_count) !== 'very-immature' && (competitor.rank ?? '')}</td>
                <td className={classNames("has-text-centered", {"has-tooltip-multiline has-tooltip-left": competitorTooltip(competitor)})} data-tooltip={competitorTooltip(competitor)}>
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
              </tr>
            ))
          }
        </tbody>
      </table>
      <button
        className="button is-info mt-2"
        onClick={calculateMatchResult}
        disabled={calculateDisabled()}
      >
        Calculate Expected Match Result
      </button>
    </div>
  );
}

export default BracketTable;