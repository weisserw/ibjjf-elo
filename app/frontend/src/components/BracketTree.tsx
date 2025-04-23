import { useMemo } from 'react';
import { referencesMatchRed, referencesMatchBlue, type Match, noMatchStrings } from "./BracketUtils"
import classNames from 'classnames';
import dayjs from 'dayjs';

import "./BracketTree.css";

interface BracketTreeMatchProps {
  match: Match;
  showSeed: boolean;
  levelIndex: number;
  numLevels: number;
}

function BracketTreeMatch(props: BracketTreeMatchProps) {
  const { match, levelIndex, numLevels } = props;

  return (
    <div className="bracket-tree-match">
      <div className="bracket-tree-match-description">
        <div className="bracket-tree-match-description-when">
          {match.when && dayjs(match.when).format('ddd h:mma')}
          {
            match.where && ' - ' + match.where
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
                    match.red_rating !== null && <span className="bracket-tree-match-rating"> ({match.red_rating}{match.red_handicap > 0 && <span className="bracket-tree-handicapped-rating has-tooltip" data-tooltip={`${match.red_weight} vs ${match.blue_weight}`}> +{match.red_handicap}</span>})</span>
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
                    match.blue_rating !== null && <span className="bracket-tree-match-rating"> ({match.blue_rating}{match.blue_handicap > 0 && <span className="bracket-tree-handicapped-rating has-tooltip" data-tooltip={`${match.red_weight} vs ${match.blue_weight}`}> +{match.blue_handicap}</span>})</span>
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
  );
}

interface BracketTreeProps {
  matches: Match[];
  showSeed: boolean;
}

function BracketTree(props: BracketTreeProps) {
  const leveledMatches = useMemo(() => {
    const levels: Match[][] = [[]];
  
    const finalMatch = props.matches.find(m => m.final);
    if (!finalMatch) {
      return levels;
    }

    const allMatches = props.matches.filter(m => !m.final);

    levels[0].push(finalMatch);

    while (allMatches.length) {
      const nextLevelMatches: Match[] = [];
      let foundMatch = false;

      for (const match of levels[levels.length - 1]) {
        const firstReferencedMatchIndex = allMatches.findIndex(m => referencesMatchRed(match, m));
        if (firstReferencedMatchIndex > -1) {
          foundMatch = true;
          nextLevelMatches.push(allMatches[firstReferencedMatchIndex]);
          allMatches.splice(firstReferencedMatchIndex, 1);
        }
        const secondReferencedMatchIndex = allMatches.findIndex(m => referencesMatchBlue(match, m));
        if (secondReferencedMatchIndex > -1) {
          foundMatch = true;
          nextLevelMatches.push(allMatches[secondReferencedMatchIndex]);
          allMatches.splice(secondReferencedMatchIndex, 1);
        }
      }

      if (!foundMatch) {
        break;
      }

      levels.push(nextLevelMatches);
    }

    return levels.reverse();
  }, [props.matches]);

  return (
    <div className="bracket-tree">
      {
        leveledMatches.map((level, levelIndex) => (
          <div key={levelIndex} className="bracket-level">
            {level.map((match, matchIndex) => (
              <BracketTreeMatch
                key={matchIndex}
                match={match}
                showSeed={props.showSeed}
                levelIndex={levelIndex}
                numLevels={leveledMatches.length}
              />
            ))}
          </div>
        ))
      }
    </div>
  );
}

export default BracketTree;