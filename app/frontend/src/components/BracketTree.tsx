import { useState, useRef, useEffect, useMemo } from 'react';
import { noMatchStrings, createTreeFromTop, createTreeFromMatchNums, type Match } from "./BracketUtils"
import classNames from 'classnames';
import dayjs from 'dayjs';
import 'dayjs/locale/pt';
import { useAppContext } from '../AppContext';
import { immatureClass } from '../utils';
import { Tooltip } from 'react-tooltip';
import { t, translateMultiSpace } from '../translate';
import igLogo from '/src/assets/instagram.png';

import "./BracketTree.css";


interface BracketTreeMatchProps {
  match: Match;
  showSeed: boolean;
  levelIndex: number;
  matchIndex: number;
  showRatings: boolean;
  calculateEnabled: (match: Match) => boolean;
  calculateClicked: (match: Match) => void;
}

function BracketTreeMatch(props: BracketTreeMatchProps) {
  const { match, levelIndex, matchIndex } = props;
  const { language } = useAppContext();

  const tooltip = (numMatches: number | null) => {
    const immature = immatureClass(numMatches);
    if (immature === '') {
      return undefined;
    }
    if (immature === 'very-immature') {
      return `${t("Athlete's rating is provisional due to insufficient matches within three years")} (${numMatches})`;
    }
    return `${t("Athlete's rating is semi-provisional due to insufficient matches within three years")} (${numMatches})`;
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
          (props.showRatings && props.calculateEnabled(match)) &&
          <button className="button is-small bracket-tree-match-calc" onClick={() => props.calculateClicked(match)}>
            <span className="icon is-small has-text-info">
              <i className="fas fa-calculator"/>
            </span>
          </button>
        }
        <div className="bracket-tree-match-description">
          <div className="bracket-tree-match-description-when">
            {match.when && dayjs(match.when).locale(language).format('ddd h:mma')}
            {
              match.when && (match.where || match.fight_num) && <span> - </span>
            }
            {
              match.fight_num && <span>{t("Fight")} {match.fight_num}</span>
            }
            {
              match.fight_num && match.when && <span>, </span>
            }
            {
              match.where && <span>{translateMultiSpace(match.where)}</span>
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
                    {match.red_instagram_profile && (
                      <span className="instagram-profile-tree">
                        <a href={`https://www.instagram.com/${match.red_instagram_profile}`} target="_blank" rel="noopener noreferrer">
                          <img src={igLogo} alt="Instagram" title={`@${match.red_instagram_profile}`} />
                        </a>
                      </span>
                    )}
                    {
                      (props.showRatings && match.red_rating !== null) &&
                        <span className="bracket-tree-match-rating"> ({Math.round(match.red_rating)}{
                          match.red_handicap > 0 && <span className="bracket-tree-handicapped-rating has-cursor-pointer" data-tooltip-id="bracket-normal-tooltip" data-tooltip-content={`${match.red_weight} vs ${match.blue_weight}`}> +{Math.round(match.red_handicap)}</span>
                        })
                        {
                          immatureClass(match.red_match_count) === 'very-immature' ?
                            <span className="has-cursor-pointer" data-tooltip-id="bracket-multiline-tooltip" data-tooltip-content={tooltip(match.red_match_count)}> <span className="very-immature-bullet">&nbsp;</span></span> : (
                              immatureClass(match.red_match_count) === 'immature' &&
                              <span className="has-cursor-pointer" data-tooltip-id="bracket-multiline-tooltip" data-tooltip-content={tooltip(match.red_match_count)}> <span className="immature-bullet">&nbsp;</span></span>
                            )
                        }
                        </span>
                    }
                  </span>
                  {
                    (props.showRatings && match.red_expected !== null) &&
                    <span className="bracket-tree-match-expected"> - {Math.round(match.red_expected * 100)}%
                    {(immatureClass(match.red_match_count) === 'very-immature' || immatureClass(match.blue_match_count) === 'very-immature') && ' (?)'}
                    </span>
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
                {match.red_note && <span className="bracket-tree-match-note has-cursor-pointer" data-tooltip-id="bracket-normal-tooltip" data-tooltip-content={match.red_note}>ℹ️</span>}
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
                    {match.blue_instagram_profile && (
                      <span className="instagram-profile-tree">
                        <a href={`https://www.instagram.com/${match.blue_instagram_profile}`} target="_blank" rel="noopener noreferrer">
                          <img src={igLogo} alt="Instagram" title={`@${match.blue_instagram_profile}`} />
                        </a>
                      </span>
                    )}
                    {
                      (props.showRatings && match.blue_rating !== null) &&
                      <span className="bracket-tree-match-rating"> ({Math.round(match.blue_rating)}{
                        match.blue_handicap > 0 && <span className="bracket-tree-handicapped-rating has-cursor-pointer" data-tooltip-id="bracket-normal-tooltip" data-tooltip-content={`${match.red_weight} vs ${match.blue_weight}`}> +{Math.round(match.blue_handicap)}</span>
                      })
                      {
                        immatureClass(match.blue_match_count) === 'very-immature' ?
                          <span className="has-cursor-pointer" data-tooltip-id="bracket-multiline-tooltip" data-tooltip-content={tooltip(match.blue_match_count)}> <span className="very-immature-bullet">&nbsp;</span></span> : (
                            immatureClass(match.blue_match_count) === 'immature' &&
                            <span className="has-cursor-pointer" data-tooltip-id="bracket-multiline-tooltip" data-tooltip-content={tooltip(match.blue_match_count)}> <span className="immature-bullet">&nbsp;</span></span>
                          )
                      }
                      </span>
                    }
                  </span>
                  {
                    (props.showRatings && match.blue_expected !== null) &&
                    <span className="bracket-tree-match-expected"> - {Math.round(match.blue_expected * 100)}%
                    {(immatureClass(match.red_match_count) === 'very-immature' || immatureClass(match.blue_match_count) === 'very-immature') && ' (?)'}
                    </span>
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
                {match.blue_note && <span className={classNames("bracket-tree-match-note")} data-tooltip-id="bracket-normal-tooltip" data-tooltip-content={match.blue_note}>ℹ️</span>}
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
  matchCount: number;
  showSeed: boolean;
  hasMatchNums: boolean;
  showRefresh: boolean;
  showRatings: boolean;
  isRefreshing?: boolean;
  calculateClicked: (match: Match) => void;
  refreshClicked?: () => void;
  calculateEnabled: (match: Match) => boolean;
}

function BracketTree(props: BracketTreeProps) {
  const [zoomLevel, setZoomLevel] = useState(.55);
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
    if (!props.hasMatchNums) {
      return createTreeFromTop(props.matches);
    } else {
      return createTreeFromMatchNums(props.matches, props.matchCount);
    }
  }, [props.matches]);

  return (
    <div className="mt-4">
      <div className="bracket-tree-slider">
        <div className="bracket-tree-slider-controls">
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
        <div className="bracket-tree-slider-refresh">
          {props.showRefresh && (
            <button disabled={props.isRefreshing} className={classNames("button is-small", {"is-loading": props.isRefreshing})} onClick={() => props.refreshClicked?.()}>
              <span className="icon is-small">
                <i className="fas fa-sync"></i>
              </span>
            </button>
          )}
        </div>
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
                      showRatings={props.showRatings}
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
      <Tooltip id="bracket-normal-tooltip" className="tooltip-normal" />
      <Tooltip id="bracket-multiline-tooltip" className="tooltip-multiline" />
    </div>
  );
}

export default BracketTree;