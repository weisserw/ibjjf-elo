import { useState, useRef, useEffect, useMemo } from 'react';
import { referencesMatchRed, referencesMatchBlue, noMatchStrings, numLevels, createBye, type Match } from "./BracketUtils"
import classNames from 'classnames';
import dayjs from 'dayjs';
import { immatureClass } from '../utils';

import "./BracketTree.css";


interface BracketTreeMatchProps {
  match: Match;
  showSeed: boolean;
  levelIndex: number;
  matchIndex: number;
  calculateEnabled: (match: Match) => boolean;
  calculateClicked: (match: Match) => void;
}

function BracketTreeMatch(props: BracketTreeMatchProps) {
  const { match, levelIndex, matchIndex } = props;

  const tooltip = (numMatches: number | null) => {
    const immature = immatureClass(numMatches);
    if (immature === '') {
      return undefined;
    }
    if (immature === 'very-immature') {
      return `Athlete's rating is provisional due to insufficient matches (${numMatches})`;
    }
    return `Athlete's rating is semi-provisional due to insufficient matches (${numMatches})`;
  }

  return (
    <div className="bracket-tree-match-container">
      <div className="bracket-tree-match">
        {
          ((levelIndex % 4) === 0) && (matchIndex > 0) && ((matchIndex % 8) === 0) && (
            <hr className="bracket-level-divider" />
          )
        }
        {
          props.calculateEnabled(match) &&
          <button className="button is-small bracket-tree-match-calc" onClick={() => props.calculateClicked(match)}>
            <span className="icon is-small has-text-info">
              <i className="fas fa-calculator"/>
            </span>
          </button>
        }
        <div className="bracket-tree-match-description">
          <div className="bracket-tree-match-description-when">
            {match.when && dayjs(match.when).format('ddd h:mma')}
            {
              match.when && (match.where || match.fight_num) && <span> - </span>
            }
            {
              match.fight_num && <span>Fight {match.fight_num}</span>
            }
            {
              match.fight_num && match.when && <span>, </span>
            }
            {
              match.where && <span>{match.where}</span>
            }
          </div>
        </div>
        <table className="bracket-tree-match-competitors">
          <tbody>
            <tr className={classNames({"bracket-tree-match-winner": match.blue_loser && !match.red_loser})}>
              <td className="bracket-tree-match-ordinal">
                {props.showSeed && match.red_seed}
                {props.showSeed && !match.red_seed && <span className="bracket-tree-match-no-ordinal">&nbsp;</span>}
                {!props.showSeed && match.red_ordinal}
                {!props.showSeed && !match.red_ordinal && <span className="bracket-tree-match-no-ordinal">&nbsp;</span>}
              </td>
              <td className="bracket-tree-match-competitor-name">
                <div className="bracket-tree-match-competitor-name-name">
                  <span className={classNames({"strike-through": noMatchStrings.some(s => match.red_note?.toLowerCase() === s)})}>
                    {match.red_name}
                    {
                      match.red_rating !== null &&
                        <span className="bracket-tree-match-rating"> ({Math.round(match.red_rating)}{
                          match.red_handicap > 0 && <span className="bracket-tree-handicapped-rating has-tooltip" data-tooltip={`${match.red_weight} vs ${match.blue_weight}`}> +{Math.round(match.red_handicap)}</span>
                        })
                        {
                          immatureClass(match.red_match_count) === 'very-immature' ?
                            <span className="has-tooltip-multiline" data-tooltip={tooltip(match.red_match_count)}> <span className="very-immature-bullet">&nbsp;</span></span> : (
                              immatureClass(match.red_match_count) === 'immature' &&
                              <span className="has-tooltip-multiline" data-tooltip={tooltip(match.red_match_count)}> <span className="immature-bullet">&nbsp;</span></span>
                            )
                        }
                        </span>
                    }
                  </span>
                  {
                    match.red_expected !== null && <span className="bracket-tree-match-expected"> - {Math.round(match.red_expected * 100)}%</span>
                  }
                  {match.red_bye && <span className="bracket-tree-match-bye">BYE</span>}
                  {match.red_next_description && <span className="bracket-tree-match-next">{match.red_next_description}</span>}
                </div>
                <div className="bracket-tree-match-competitor-name-team">
                  {match.red_team}
                  {!match.red_team && <span className="bracket-tree-match-no-team">&nbsp;</span>}
                </div>
              </td>
              <td className="bracket-tree-match-info">
                {match.red_medal === "1" && <span>🥇</span>}
                {match.red_medal === "2" && <span>🥈</span>}
                {match.red_medal === "3" && <span>🥉</span>}
                {match.red_note && <span className={classNames("bracket-tree-match-note has-tooltip", {"has-tooltip-right": levelIndex === 0})} data-tooltip={match.red_note}>ℹ️</span>}
              </td>
            </tr>
            <tr className={classNames({"bracket-tree-match-winner": match.red_loser && !match.blue_loser})}>
              <td className="bracket-tree-match-ordinal">
                {props.showSeed && match.blue_seed}
                {props.showSeed && !match.blue_seed && <span className="bracket-tree-match-no-ordinal">&nbsp;</span>}
                {!props.showSeed && match.blue_ordinal}
                {!props.showSeed && !match.blue_ordinal && <span className="bracket-tree-match-no-ordinal">&nbsp;</span>}
              </td>
              <td className="bracket-tree-match-competitor-name">
              <div className="bracket-tree-match-competitor-name-name">
                  <span className={classNames({"strike-through": noMatchStrings.some(s => match.blue_note?.toLowerCase() === s)})}>
                    {match.blue_name}
                    {
                      match.blue_rating !== null &&
                      <span className="bracket-tree-match-rating"> ({Math.round(match.blue_rating)}{
                        match.blue_handicap > 0 && <span className="bracket-tree-handicapped-rating has-tooltip" data-tooltip={`${match.red_weight} vs ${match.blue_weight}`}> +{Math.round(match.blue_handicap)}</span>
                      })
                      {
                        immatureClass(match.blue_match_count) === 'very-immature' ?
                          <span className="has-tooltip-multiline" data-tooltip={tooltip(match.blue_match_count)}> <span className="very-immature-bullet">&nbsp;</span></span> : (
                            immatureClass(match.blue_match_count) === 'immature' &&
                            <span className="has-tooltip-multiline" data-tooltip={tooltip(match.blue_match_count)}> <span className="immature-bullet">&nbsp;</span></span>
                          )
                      }
                      </span>
                    }
                  </span>
                  {
                    match.blue_expected !== null && <span className="bracket-tree-match-expected"> - {Math.round(match.blue_expected * 100)}%</span>
                  }
                  {match.blue_bye && <span className="bracket-tree-match-bye">BYE</span>}
                  {match.blue_next_description && <span className="bracket-tree-match-next">{match.blue_next_description}</span>}
                </div>
                <div className="bracket-tree-match-competitor-name-team">
                  {match.blue_team}
                  {!match.blue_team && <span className="bracket-tree-match-no-team">&nbsp;</span>}
                </div>
              </td>
              <td className="bracket-tree-match-info">
                {match.blue_medal === "1" && <span>🥇</span>}
                {match.blue_medal === "2" && <span>🥈</span>}
                {match.blue_medal === "3" && <span>🥉</span>}
                {match.blue_note && <span className={classNames("bracket-tree-match-note has-tooltip", {"has-tooltip-right": levelIndex === 0})} data-tooltip={match.blue_note}>ℹ️</span>}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface BracketTreeProps {
  matches: Match[];
  showSeed: boolean;
  createByes: boolean;
  calculateClicked: (match: Match) => void;
  calculateEnabled: (match: Match) => boolean;
}

function BracketTree(props: BracketTreeProps) {
  const [zoomLevel, setZoomLevel] = useState(.9);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const [naturalWidth, setNaturalWidth] = useState<number | null>(null);

  const handleZoomChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setZoomLevel(Number(event.target.value));
  };

  const updateNaturalWidth = () => {
    const container = scrollContainerRef.current;
    if (container) {
      setNaturalWidth(container.offsetWidth);
    }
  };

  useEffect(() => {
    updateNaturalWidth();
  }, [props.matches]);

  useEffect(() => {
    window.addEventListener('resize', updateNaturalWidth);
    return () => {
      window.removeEventListener('resize', updateNaturalWidth);
    };
  }, []);

  const leveledMatches = useMemo(() => {
    const levels: Match[][] = [[]];

    // sort in reverse order by date
    const sortedMatches = [...props.matches].sort((a, b) => {
      return (b.when || '').localeCompare(a.when || '');
    });
  
    const finalMatch = sortedMatches.find(m => m.final);
    if (!finalMatch) {
      return levels;
    }
    const allMatches = sortedMatches.filter(m => !m.final);

    levels[0].push(finalMatch);

    while (allMatches.length) {
      const nextLevelMatches: Match[] = [];
      let missingMatches = 0;

      for (const match of levels[levels.length - 1]) {
        const firstReferencedMatchIndex = allMatches.findIndex(m => referencesMatchRed(match, m));
        if (firstReferencedMatchIndex > -1) {
          nextLevelMatches.push(allMatches[firstReferencedMatchIndex]);
          allMatches.splice(firstReferencedMatchIndex, 1);
        } else {
          if (props.createByes && props.matches.length > 4 && levels.length + 1 === numLevels(props.matches.length)) {
            nextLevelMatches.push(createBye(match.red_id, match.red_name, match.red_team,
              match.red_seed, match.red_ordinal, match.red_weight, match.red_rating, match.red_match_count));
          } else {
            missingMatches++;
          }
        }
        const secondReferencedMatchIndex = allMatches.findIndex(m => referencesMatchBlue(match, m));
        if (secondReferencedMatchIndex > -1) {
          nextLevelMatches.push(allMatches[secondReferencedMatchIndex]);
          allMatches.splice(secondReferencedMatchIndex, 1);
        } else {
          if (props.createByes && props.matches.length > 4 && levels.length + 1 === numLevels(props.matches.length)) {
            nextLevelMatches.push(createBye(match.blue_id, match.blue_name, match.blue_team,
              match.blue_seed, match.blue_ordinal, match.blue_weight, match.blue_rating, match.blue_match_count));
          } else {
            missingMatches++;
          }
        }
      }

      // If we weren't able to find ancestors for all matches,
      // just guess that the next matches by date are in this level
      if (missingMatches > 0) {
        nextLevelMatches.push(...allMatches.splice(0, missingMatches));
      }

      levels.push(nextLevelMatches);
    }

    return levels.reverse();
  }, [props.matches]);

  return (
    <div>
      <div className="bracket-tree-slider">
        <span className="icon cursor-pointer" onClick={() => setZoomLevel(Math.max(0.2, zoomLevel - 0.05))}>
          <i className="fas fa-magnifying-glass-minus"></i>
        </span>
        <input
          id="zoom-slider"
          type="range"
          min="0.2"
          max="0.9"
          step="0.05"
          value={zoomLevel}
          onChange={handleZoomChange}
        />
        <span className="icon cursor-pointer" onClick={() => setZoomLevel(Math.min(1, zoomLevel + 0.05))}>
          <i className="fas fa-magnifying-glass-plus"></i>
        </span>
      </div>
      <div className="bracket-tree-border" ref={scrollContainerRef}>
        <div
          style={{
            overflow: 'visible',
            transformOrigin: '0 0',
            transform: `scale(${zoomLevel})`,
            width: naturalWidth ? `${naturalWidth * zoomLevel}px` : 'fit-content',
            height: `${640 * zoomLevel}px`,
          }}
        >
          <div className="bracket-tree">
            {
              leveledMatches.map((level, levelIndex) => (
                <div key={levelIndex} className="bracket-level" style={{
                  height: `${155 * leveledMatches[4 * Math.floor(levelIndex/4)].length}px`
                }}>
                  {level.map((match, matchIndex) => (
                    <BracketTreeMatch
                      key={matchIndex}
                      match={match}
                      showSeed={props.showSeed}
                      levelIndex={levelIndex}
                      calculateClicked={props.calculateClicked}
                      calculateEnabled={props.calculateEnabled}
                      matchIndex={matchIndex}
                    />
                  ))}
                  {
                    (levelIndex > 0) && (levelIndex % 4) === 0 && (
                      <hr key={`${levelIndex}-divider`} className="bracket-tree-divider" />
                    )
                  }
                </div>
              ))
            }
          </div>
        </div>
      </div>
    </div>
  );
}

export default BracketTree;