import axios, { type AxiosError } from 'axios'
import { remove } from 'lodash'

export interface Competitor {
  ordinal: number
  id: string | null
  ibjjf_id: string | null
  seed: number
  name: string
  team: string
  rating: number | null
  end_rating: number | null
  match_count: number | null
  end_match_count: number | null
  rank: number | null
  note: string | null
  last_weight: string | null
  medal?: string
}

export interface Match {
  match_num: number | null
  final: boolean
  when: string | null
  where: string | null
  fight_num: number | null
  red_bye: boolean
  red_id: string | null
  red_seed: number | null
  red_loser: boolean | null
  red_name: string | null
  red_team: string | null
  red_note: string | null
  red_next_description: string | null
  red_ordinal: number | null
  red_expected: number | null
  red_rating: number | null
  red_handicap: number
  red_weight: string | null
  red_medal: string | null
  red_match_count: number | null
  blue_bye: boolean
  blue_id: string | null
  blue_seed: number | null
  blue_loser: boolean | null
  blue_name: string | null
  blue_team: string | null
  blue_note: string | null
  blue_next_description: string | null
  blue_ordinal: number | null
  blue_expected: number | null
  blue_rating: number | null
  blue_handicap: number
  blue_weight: string | null
  blue_medal: string | null
  blue_match_count: number | null
}

export interface CompetitorsResponse {
  error?: string
  competitors?: Competitor[]
}


export interface Category {
  link?: string
  age: string
  belt: string
  weight: string
  gender: string
}

export interface CategoriesResponse {
  error?: string
  categories?: Category[]
}

export interface LiveCompetitorsResponse extends CompetitorsResponse {
  matches?: Match[]
}

export const categoryString = (category: Category) => {
  return `${category.belt} / ${category.age} / ${category.gender} / ${category.weight}`
}

export const isGi = (name: string) => {
  return !/no[ -]gi/.test(name.toLowerCase()) && !/sem kimono/.test(name.toLowerCase());
}

export const handleError = (err: any, errFunc: (error: string) => void) => {
  if (axios.isAxiosError(err)) {
    const axiosError = err as AxiosError<any>;
    if (axiosError.response?.data?.error) {
      errFunc(axiosError.response.data.error);
    } else {
      errFunc(axiosError.message);
    }
  } else {
    errFunc(JSON.stringify(err));
  }
}

// return true if the match red competitor references another
// a reference can take two forms: a competitor has the same seed
// or there is next description of "winner or fight N mat M" that matches
// the fight_num and where of the other

export const referencesMatchRed = (match: Match, other: Match) => {
  if (!match.red_bye && match.red_seed !== null) {
    if (!other.red_bye && match.red_seed === other.red_seed) {
      return true;
    }
    if (!other.blue_bye && match.red_seed === other.blue_seed) {
      return true;
    }
  }
  if (match.red_next_description && other.fight_num !== null && other.where !== null) {
    if (match.red_next_description.toLowerCase().endsWith(`of fight ${other.fight_num}, ${other.where.toLowerCase()}`) ||
        match.red_next_description.toLowerCase().endsWith(`da luta ${other.fight_num}, ${other.where.toLowerCase()}`)) {
      return true;
    }
  }
  return false;
}

export const referencesMatchBlue = (match: Match, other: Match) => {
  if (!match.blue_bye && match.blue_seed !== null) {
    if (!other.red_bye && match.blue_seed === other.red_seed) {
      return true;
    }
    if (!other.blue_bye && match.blue_seed === other.blue_seed) {
      return true;
    }
  }
  if (match.blue_next_description && other.fight_num !== null && other.where !== null) {
    if (match.blue_next_description.toLowerCase().endsWith(`of fight ${other.fight_num}, ${other.where.toLowerCase()}`) ||
        match.blue_next_description.toLowerCase().endsWith(`da luta ${other.fight_num}, ${other.where.toLowerCase()}`)) {
      return true;
    }
  }
  return false;
}

export const noMatchStrings = [
  "disqualified by no show",
  "disqualified by overweight",
  "disqualified by acima do peso",
  "disqualified by withdraw",
];

export const numLevels = (n: number) => {
  return Math.ceil(Math.log2(n));
}

export const createBye = (id: string | null, name: string | null, team: string | null,
  seed: number | null, ordinal: number | null, weight: string | null, rating: number | null,
  match_count: number | null): Match => {
  return {
    match_num: null,
    final: false,
    when: null,
    where: null,
    fight_num: null,
    red_id: id,
    red_name: name,
    red_team: team,
    red_bye: false,
    red_seed: seed,
    red_loser: false,
    red_note: null,
    red_next_description: null,
    red_medal: null,
    red_ordinal: ordinal,
    red_weight: weight,
    red_handicap: 0,
    red_expected: null,
    red_rating: rating,
    red_match_count: match_count,
    blue_id: null,
    blue_name: null,
    blue_team: null,
    blue_bye: true,
    blue_seed: null,
    blue_loser: false,
    blue_note: null,
    blue_next_description: null,
    blue_medal: null,
    blue_ordinal: null,
    blue_weight: null,
    blue_handicap: 0,
    blue_expected: null,
    blue_rating: null,
    blue_match_count: null,
  }
}

export const createTreeFromMatchNums = (matches: Match[]): Match[][] => {
  const levels: Match[][] = [];

  // sort in order by match_num
  const allMatches = [...matches].sort((a, b) => {
    return (a.match_num ?? 0) - (b.match_num ?? 0);
  });

  const levelCount = numLevels(allMatches.length);

  for (let i = 0; i < levelCount; i++) {
    const levelMatches: Match[] = [];
    const numMatches = Math.pow(2, levelCount - i - 1);
    for (let j = 0; j < numMatches; j++) {
      if (allMatches.length > 0) {
        levelMatches.push(allMatches.shift()!);
      }
    }
    levels.push(levelMatches);
  }

  return levels;
}

export const createTreeFromTop = (matches: Match[]): Match[][] => {
  const levels: Match[][] = [[]];

  // sort in reverse order by date
  const sortedMatches = [...matches].sort((a, b) => {
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

    // not enough matches to fill the next level
    if (levels.length > 0 && allMatches.length < levels[levels.length - 1].length * 2) {
      break;
    }

    let removed = 0;

    for (const match of levels[levels.length - 1]) {
      const firstReferencedMatchIndex = allMatches.findIndex(m => referencesMatchRed(match, m));
      if (firstReferencedMatchIndex > -1) {
        nextLevelMatches.push(allMatches[firstReferencedMatchIndex]);
        allMatches.splice(firstReferencedMatchIndex, 1);
        removed++;
      } else if (matches.length > 4 && levels.length + 1 === numLevels(matches.length)) {
        nextLevelMatches.push(createBye(match.red_id, match.red_name, match.red_team,
          match.red_seed, match.red_ordinal, match.red_weight, match.red_rating, match.red_match_count));
      }
      const secondReferencedMatchIndex = allMatches.findIndex(m => referencesMatchBlue(match, m));
      if (secondReferencedMatchIndex > -1) {
        nextLevelMatches.push(allMatches[secondReferencedMatchIndex]);
        allMatches.splice(secondReferencedMatchIndex, 1);
        removed++;
      } else if (matches.length > 4 && levels.length + 1 === numLevels(matches.length)) {
          nextLevelMatches.push(createBye(match.blue_id, match.blue_name, match.blue_team,
            match.blue_seed, match.blue_ordinal, match.blue_weight, match.blue_rating, match.blue_match_count));
      }
    }

    if (removed === 0) {
      break;
    }

    levels.push(nextLevelMatches);
  }

  return levels.reverse();
}