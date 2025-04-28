import axios, { type AxiosError } from 'axios'

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

