import axios, { type AxiosError } from 'axios'

export interface Competitor {
  ordinal: number
  id: string | null
  ibjjf_id: string | null
  seed: number
  name: string
  slug: string
  team: string
  instagram_profile: string | null
  personal_name: string | null
  profile_image_url: string | null
  country: string | null
  country_note: string | null
  country_note_pt: string | null
  rating: number | null
  end_rating: number | null
  match_count: number | null
  end_match_count: number | null
  rank: number | null
  percentile: number | null
  percentile_age: string | null
  note: string | null
  last_weight: string | null
  next_where: string | null
  next_when: string | null
  medal?: string
  est_seed?: number | null
  est_seed_tied?: boolean
  points?: number
  open_class_points?: number
  grand_slam_points?: number
  grand_slam_open_class_points?: number
  world_champion_recent?: boolean
  last_world_title_year?: number | null
  world_champion_4_years_ago?: boolean
  world_champion_5_years_ago?: boolean
  previous_brown_world_champion?: boolean
  former_world_champion?: number | null
  adult_world_champion?: boolean
  master_1_world_champion?: boolean
  master_2_world_champion?: boolean
  master_3_world_champion?: boolean
  master_4_world_champion?: boolean
  master_5_world_champion?: boolean
  master_6_world_champion?: boolean
  master_7_world_champion?: boolean
}

export interface Match {
  match_num: number | null
  final: boolean
  when: string | null
  where: string | null
  fight_num: number | null
  video_link: string | null
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
  red_instagram_profile: string | null
  red_personal_name: string | null
  red_profile_image_url: string | null
  red_country: string | null
  red_country_note: string | null
  red_country_note_pt: string | null
  red_percentile: number | null
  red_percentile_age: string | null
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
  blue_instagram_profile: string | null
  blue_personal_name: string | null
  blue_profile_image_url: string | null
  blue_country: string | null
  blue_country_note: string | null
  blue_country_note_pt: string | null
  blue_percentile: number | null
  blue_percentile_age: string | null
}

export interface SideSwap {
  name_a: string
  name_b: string
}

export interface CompetitorsResponse {
  error?: string
  competitors?: Competitor[]
  side_swaps?: SideSwap[]
  side_swap_bailout_teams?: string[]
  bracket_slots?: [number, number | null][] | null
  bracket_match_count?: number | null
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
  total?: number
}

export interface AthleteMedalDetail {
  event_name: string
  division_age: string
  division_weight: string
  place: number
  base_points: number
  star: number
  season_mult: number
  weight_mult: number
  total: number
  happened_at: string | null
  bucket: 'weight' | 'open'
}

export interface MedalBreakdownBucket {
  medals: AthleteMedalDetail[]
  points_total: number
  open_class_points_total: number
}

export interface MedalBreakdownResponse {
  points?: MedalBreakdownBucket
  grand_slam?: MedalBreakdownBucket
  error?: string
}

export type MatNumberString = string

export type MatLinkType = 'youtube' | 'flo'

export interface MatLinkEntry {
  link: string
  type: MatLinkType
}

export type MatLink = Record<MatNumberString, MatLinkEntry>

export type TournamentDate = string

export type MatLinks = Record<TournamentDate, MatLink>

export interface LiveCompetitorsResponse extends CompetitorsResponse {
  matches?: Match[]
  mat_links?: MatLinks
}

export const categoryString = (category: Category) => {
  return `${category.belt} / ${category.age} / ${category.gender} / ${category.weight}`
}

export const isGi = (name: string) => {
  return !/no[ -]gi/.test(name.toLowerCase()) && !/sem kimono/.test(name.toLowerCase());
}

interface ErrorResponse {
  error?: string
}

export const handleError = (err: unknown, errFunc: (error: string) => void) => {
  if (axios.isAxiosError(err)) {
    const axiosError = err as AxiosError<ErrorResponse>;
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

export const numLevels = (n: number) => {
  if (n === 1) {
    return 1;
  }
  return Math.ceil(Math.log2(n));
}

export const nearestPowerOfTwo = (n: number) => {
  if (n <= 4) {
    return n;
  }
  let power = 1;
  while (power < n) {
    power *= 2;
  }
  return power;
}  

export const createBye = (id: string | null, name: string | null, team: string | null,
  instagram_profile: string | null, personal_name: string | null,
  profile_image_url: string | null,
  country: string | null, country_note: string | null, country_note_pt: string | null,
  seed: number | null, ordinal: number | null, weight: string | null,
  rating: number | null, match_count: number | null, note: string | null, percentile: number | null, percentile_age: string | null): Match => {
  return {
    match_num: null,
    final: false,
    when: null,
    where: null,
    fight_num: null,
    video_link: null,
    red_id: id,
    red_name: name,
    red_team: team,
    red_bye: false,
    red_seed: seed,
    red_loser: false,
    red_note: note,
    red_next_description: null,
    red_medal: null,
    red_ordinal: ordinal,
    red_weight: weight,
    red_handicap: 0,
    red_expected: null,
    red_rating: rating,
    red_match_count: match_count,
    red_instagram_profile: instagram_profile,
    red_personal_name: personal_name,
    red_profile_image_url: profile_image_url,
    red_country: country,
    red_country_note: country_note,
    red_country_note_pt: country_note_pt,
    red_percentile: percentile,
    red_percentile_age: percentile_age,
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
    blue_instagram_profile: null,
    blue_personal_name: null,
    blue_profile_image_url: null,
    blue_country: null,
    blue_country_note: null,
    blue_country_note_pt: null,
    blue_percentile: null,
    blue_percentile_age: null
  }
}

const createEmptyMatch = (match_num: number): Match => {
  return {
    match_num,
    final: false,
    when: null,
    where: null,
    fight_num: null,
    video_link: null,
    red_bye: false,
    red_id: null,
    red_seed: null,
    red_loser: false,
    red_name: null,
    red_team: null,
    red_note: null,
    red_next_description: null,
    red_medal: null,
    red_ordinal: null,
    red_weight: null,
    red_handicap: 0,
    red_expected: null,
    red_rating: null,
    red_match_count: null,
    red_instagram_profile: null,
    red_personal_name: null,
    red_profile_image_url: null,
    red_country: null,
    red_country_note: null,
    red_country_note_pt: null,
    red_percentile: null,
    red_percentile_age: null,
    blue_bye: false,
    blue_id: null,
    blue_seed: null,
    blue_loser: false,
    blue_name: null,
    blue_team: null,
    blue_note: null,
    blue_next_description: null,
    blue_medal: null,
    blue_ordinal: null,
    blue_weight: null,
    blue_handicap: 0,
    blue_expected: null,
    blue_rating: null,
    blue_match_count: null,
    blue_instagram_profile: null,
    blue_personal_name: null,
    blue_profile_image_url: null,
    blue_country: null,
    blue_country_note: null,
    blue_country_note_pt: null,
    blue_percentile: null,
    blue_percentile_age: null
  }
}

export const createTreeFromMatchNums = (matches: Match[], matchCount: number): Match[][] => {
  const levels: Match[][] = [];

  // sort in order by match_num
  const allMatches = [...matches].sort((a, b) => {
    return (a.match_num ?? 0) - (b.match_num ?? 0);
  });

  // insert empty matches if any match_num is missing
  for (let i = 0; i < allMatches.length; i++) {
    while (allMatches[i].match_num !== i + 1) {
      const emptyMatch = createEmptyMatch(i + 1);
      allMatches.splice(i, 0, emptyMatch);
      i++;
    }
  }

  // insert empty matches at the end if there are any missing
  for (let i = allMatches.length; i < matchCount; i++) {
    const emptyMatch = createEmptyMatch(i + 1);
    allMatches.push(emptyMatch);
  }

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

    if (levels.length === 2) {
      // if there are any athletes in the second level with no matches in the first level,
      // and a blank match is directly below them, replace the blank match with a bye
      for (let k = 0; k < levels[1].length; k++) {
        const match = levels[1][k];
        if (match.red_id !== null && !levels[0].some(m => m.red_id === match.red_id || m.blue_id === match.red_id)) {
          let possibleEmpty = levels[0][k * 2];
          if (possibleEmpty.red_id === null && possibleEmpty.blue_id === null) {
            levels[0][k * 2] = createBye(match.red_id, match.red_name, match.red_team, match.red_instagram_profile, match.red_personal_name, match.red_profile_image_url,
              match.red_country, match.red_country_note, match.red_country_note_pt,
              match.red_seed, match.red_ordinal, match.red_weight, match.red_rating, match.red_match_count, match.red_note, match.red_percentile, match.red_percentile_age);
          } else {
            possibleEmpty = levels[0][k * 2 + 1];
            if (possibleEmpty.red_id === null && possibleEmpty.blue_id === null) {
              levels[0][k * 2 + 1] = createBye(match.red_id, match.red_name, match.red_team, match.red_instagram_profile, match.red_personal_name, match.red_profile_image_url,
                match.red_country, match.red_country_note, match.red_country_note_pt,
                match.red_seed, match.red_ordinal, match.red_weight, match.red_rating, match.red_match_count, match.red_note, match.red_percentile, match.red_percentile_age);
            }
          }
        }
        if (match.blue_id !== null && !levels[0].some(m => m.red_id === match.blue_id || m.blue_id === match.blue_id)) {
          let possibleEmpty = levels[0][k * 2];
          if (possibleEmpty.red_id === null && possibleEmpty.blue_id === null) {
            levels[0][k * 2] = createBye(match.blue_id, match.blue_name, match.blue_team, match.blue_instagram_profile, match.blue_personal_name, match.blue_profile_image_url,
              match.blue_country, match.blue_country_note, match.blue_country_note_pt,
              match.blue_seed, match.blue_ordinal, match.blue_weight, match.blue_rating, match.blue_match_count, match.blue_note, match.blue_percentile, match.blue_percentile_age);
          } else {
            possibleEmpty = levels[0][k * 2 + 1];
            if (possibleEmpty.red_id === null && possibleEmpty.blue_id === null) {
              levels[0][k * 2 + 1] = createBye(match.blue_id, match.blue_name, match.blue_team, match.blue_instagram_profile, match.blue_personal_name, match.blue_profile_image_url,
                match.blue_country, match.blue_country_note, match.blue_country_note_pt,
                match.blue_seed, match.blue_ordinal, match.blue_weight, match.blue_rating, match.blue_match_count, match.blue_note, match.blue_percentile, match.blue_percentile_age);
            }
          }
        }
      }
    }
  }

  return levels;
}


interface AdvancingAthlete {
  id: string | null
  seed: number | null
  name: string | null
  team: string | null
  note: string | null
  ordinal: number | null
  rating: number | null
  match_count: number | null
  instagram_profile: string | null
  personal_name: string | null
  profile_image_url: string | null
  country: string | null
  country_note: string | null
  country_note_pt: string | null
  percentile: number | null
  percentile_age: string | null
  weight: string | null
  medal: string | null
}

const getAdvancingAthlete = (source: Match, sourceSide: MatchSide): AdvancingAthlete => {
  if (sourceSide === 'red') {
    return {
      id: source.red_id,
      seed: source.red_seed,
      name: source.red_name,
      team: source.red_team,
      note: source.red_note,
      ordinal: source.red_ordinal,
      rating: source.red_rating,
      match_count: source.red_match_count,
      instagram_profile: source.red_instagram_profile,
      personal_name: source.red_personal_name,
      profile_image_url: source.red_profile_image_url,
      country: source.red_country,
      country_note: source.red_country_note,
      country_note_pt: source.red_country_note_pt,
      percentile: source.red_percentile,
      percentile_age: source.red_percentile_age,
      weight: source.red_weight,
      medal: source.red_medal,
    };
  }

  return {
    id: source.blue_id,
    seed: source.blue_seed,
    name: source.blue_name,
    team: source.blue_team,
    note: source.blue_note,
    ordinal: source.blue_ordinal,
    rating: source.blue_rating,
    match_count: source.blue_match_count,
    instagram_profile: source.blue_instagram_profile,
    personal_name: source.blue_personal_name,
    profile_image_url: source.blue_profile_image_url,
    country: source.blue_country,
    country_note: source.blue_country_note,
    country_note_pt: source.blue_country_note_pt,
    percentile: source.blue_percentile,
    percentile_age: source.blue_percentile_age,
    weight: source.blue_weight,
    medal: source.blue_medal,
  };
}

const setAdvancingAthlete = (target: Match, targetSide: MatchSide, athlete: AdvancingAthlete) => {
  if (targetSide === 'red') {
    target.red_id = athlete.id;
    target.red_seed = athlete.seed;
    target.red_name = athlete.name;
    target.red_team = athlete.team;
    target.red_note = athlete.note;
    target.red_ordinal = athlete.ordinal;
    target.red_rating = athlete.rating;
    target.red_match_count = athlete.match_count;
    target.red_instagram_profile = athlete.instagram_profile;
    target.red_personal_name = athlete.personal_name;
    target.red_profile_image_url = athlete.profile_image_url;
    target.red_country = athlete.country;
    target.red_country_note = athlete.country_note;
    target.red_country_note_pt = athlete.country_note_pt;
    target.red_percentile = athlete.percentile;
    target.red_percentile_age = athlete.percentile_age;
    target.red_weight = athlete.weight;
    target.red_medal = athlete.medal;
    return;
  }

  target.blue_id = athlete.id;
  target.blue_seed = athlete.seed;
  target.blue_name = athlete.name;
  target.blue_team = athlete.team;
  target.blue_note = athlete.note;
  target.blue_ordinal = athlete.ordinal;
  target.blue_rating = athlete.rating;
  target.blue_match_count = athlete.match_count;
  target.blue_instagram_profile = athlete.instagram_profile;
  target.blue_personal_name = athlete.personal_name;
  target.blue_profile_image_url = athlete.profile_image_url;
  target.blue_country = athlete.country;
  target.blue_country_note = athlete.country_note;
  target.blue_country_note_pt = athlete.country_note_pt;
  target.blue_percentile = athlete.percentile;
  target.blue_percentile_age = athlete.percentile_age;
  target.blue_weight = athlete.weight;
  target.blue_medal = athlete.medal;
}

type MatchSide = 'red' | 'blue';

const copyAdvancingAthlete = (
  target: Match, targetSide: MatchSide,
  source: Match, sourceSide: MatchSide,
) => {
  setAdvancingAthlete(target, targetSide, getAdvancingAthlete(source, sourceSide));
}

const sideHasCompetitor = (match: Match, side: MatchSide) => {
  if (side === 'red') {
    return !match.red_bye && (
      match.red_id !== null ||
      match.red_seed !== null ||
      match.red_name !== null
    );
  }

  return !match.blue_bye && (
    match.blue_id !== null ||
    match.blue_seed !== null ||
    match.blue_name !== null
  );
}

const sideHasEntry = (match: Match, side: MatchSide) => {
  if (side === 'red') {
    return sideHasCompetitor(match, side) || match.red_next_description !== null;
  }

  return sideHasCompetitor(match, side) || match.blue_next_description !== null;
}

const fillSideFromParent = (target: Match, targetSide: 'red' | 'blue', parent: Match) => {
  if (parent.fight_num !== null) {
    if (targetSide === 'red') {
      target.red_next_description = `Winner of Fight ${parent.fight_num}`;
    } else {
      target.blue_next_description = `Winner of Fight ${parent.fight_num}`;
    }
    return;
  }
  const parentRedCompetitor = sideHasCompetitor(parent, 'red');
  const parentBlueCompetitor = sideHasCompetitor(parent, 'blue');
  const parentRedFilled = parentRedCompetitor || parent.red_next_description !== null;
  const parentBlueFilled = parentBlueCompetitor || parent.blue_next_description !== null;
  if (parentRedFilled && !parentBlueFilled) {
    if (parentRedCompetitor) {
      copyAdvancingAthlete(target, targetSide, parent, 'red');
    } else if (targetSide === 'red') {
      target.red_next_description = parent.red_next_description;
    } else {
      target.blue_next_description = parent.red_next_description;
    }
  } else if (parentBlueFilled && !parentRedFilled) {
    if (parentBlueCompetitor) {
      copyAdvancingAthlete(target, targetSide, parent, 'blue');
    } else if (targetSide === 'red') {
      target.red_next_description = parent.blue_next_description;
    } else {
      target.blue_next_description = parent.blue_next_description;
    }
  }
}

export const createMatchesFromSeeds = (
  competitors: Competitor[],
  bracketSlots: [number, number | null][],
  matchCount: number,
  sideSwaps: SideSwap[] = [],
  seedOf: (c: Competitor) => number | null | undefined = (c) => c.est_seed,
): { matches: Match[]; matchCount: number } | null => {
  const seeded = competitors.filter(c => {
    const s = seedOf(c);
    return s != null && s > 0;
  });
  if (seeded.length < 2) return null;

  const bySeed = new Map<number, Competitor>();
  for (const c of seeded) bySeed.set(seedOf(c)!, c);

  let nextMatchNum = 1;
  let nextFightNum = 1;

  // Resolve seeds → competitor slots, then apply side swaps. The seed number
  // stays with the competitor object, so swapping the competitors between two
  // slots moves the athletes without changing the seeds shown.
  const firstRoundSlots: [Competitor | null, Competitor | null][] =
    bracketSlots.map(([redSeed, blueSeed]) => [
      redSeed !== null ? (bySeed.get(redSeed) ?? null) : null,
      blueSeed !== null ? (bySeed.get(blueSeed) ?? null) : null,
    ]);

  for (const swap of sideSwaps) {
    let posA: [number, 0 | 1] | null = null;
    let posB: [number, 0 | 1] | null = null;
    for (let i = 0; i < firstRoundSlots.length; i++) {
      const [r, b] = firstRoundSlots[i];
      if (r && r.name === swap.name_a) posA = [i, 0];
      else if (b && b.name === swap.name_a) posA = [i, 1];
      if (r && r.name === swap.name_b) posB = [i, 0];
      else if (b && b.name === swap.name_b) posB = [i, 1];
    }
    if (posA && posB) {
      const a = firstRoundSlots[posA[0]][posA[1]];
      const b = firstRoundSlots[posB[0]][posB[1]];
      firstRoundSlots[posA[0]][posA[1]] = b;
      firstRoundSlots[posB[0]][posB[1]] = a;
    }
  }

  const firstRound: Match[] = firstRoundSlots.map(([red, blue]) => {
    return {
      match_num: nextMatchNum++,
      final: false,
      when: null,
      where: null,
      fight_num: null,
      video_link: null,

      red_bye: red === null && blue !== null,
      red_id: red?.id ?? null,
      red_seed: red ? seedOf(red)! : null,
      red_loser: false,
      red_name: red?.name ?? null,
      red_team: red?.team ?? null,
      red_note: red?.note ?? null,
      red_next_description: null,
      red_medal: red?.medal ?? null,
      red_ordinal: red?.ordinal ?? null,
      red_weight: red?.last_weight ?? null,
      red_handicap: 0,
      red_expected: null,
      red_rating: red?.rating ?? null,
      red_match_count: red?.match_count ?? null,
      red_instagram_profile: red?.instagram_profile ?? null,
      red_personal_name: red?.personal_name ?? null,
      red_profile_image_url: red?.profile_image_url ?? null,
      red_country: red?.country ?? null,
      red_country_note: red?.country_note ?? null,
      red_country_note_pt: red?.country_note_pt ?? null,
      red_percentile: red?.percentile ?? null,
      red_percentile_age: red?.percentile_age ?? null,

      blue_bye: blue === null && red !== null,
      blue_id: blue?.id ?? null,
      blue_seed: blue ? seedOf(blue)! : null,
      blue_loser: false,
      blue_name: blue?.name ?? null,
      blue_team: blue?.team ?? null,
      blue_note: blue?.note ?? null,
      blue_next_description: null,
      blue_medal: blue?.medal ?? null,
      blue_ordinal: blue?.ordinal ?? null,
      blue_weight: blue?.last_weight ?? null,
      blue_handicap: 0,
      blue_expected: null,
      blue_rating: blue?.rating ?? null,
      blue_match_count: blue?.match_count ?? null,
      blue_instagram_profile: blue?.instagram_profile ?? null,
      blue_personal_name: blue?.personal_name ?? null,
      blue_profile_image_url: blue?.profile_image_url ?? null,
      blue_country: blue?.country ?? null,
      blue_country_note: blue?.country_note ?? null,
      blue_country_note_pt: blue?.country_note_pt ?? null,
      blue_percentile: blue?.percentile ?? null,
      blue_percentile_age: blue?.percentile_age ?? null,
    };
  });

  for (const m of firstRound) {
    if (sideHasCompetitor(m, 'red') && sideHasCompetitor(m, 'blue')) {
      m.fight_num = nextFightNum++;
    }
  }

  const allMatches: Match[] = [...firstRound];
  let prevLevel: Match[] = firstRound;

  while (prevLevel.length > 1) {
    const currentLevel: Match[] = [];
    for (let j = 0; j < prevLevel.length / 2; j++) {
      const redParent = prevLevel[2 * j];
      const blueParent = prevLevel[2 * j + 1];
      const m = createEmptyMatch(nextMatchNum++);
      fillSideFromParent(m, 'red', redParent);
      fillSideFromParent(m, 'blue', blueParent);

      const redFilled = sideHasEntry(m, 'red');
      const blueFilled = sideHasEntry(m, 'blue');
      if (redFilled && blueFilled) {
        m.fight_num = nextFightNum++;
      } else if (redFilled && !blueFilled) {
        m.blue_bye = true;
      } else if (blueFilled && !redFilled) {
        m.red_bye = true;
      }

      currentLevel.push(m);
    }
    allMatches.push(...currentLevel);
    prevLevel = currentLevel;
  }

  return { matches: allMatches, matchCount };
}

const snakeSeedOrder = (size: number): number[] => {
  if (size <= 1) return [1];

  const previous = snakeSeedOrder(size / 2);
  const result: number[] = [];
  for (const seed of previous) {
    result.push(seed, size + 1 - seed);
  }
  return result;
}

export const createSnakeBracketSlots = (competitorCount: number): {
  bracketSlots: [number, number | null][];
  matchCount: number;
} | null => {
  if (competitorCount < 2) return null;

  let bracketSize = 2;
  while (bracketSize < competitorCount) {
    bracketSize *= 2;
  }

  const order = snakeSeedOrder(bracketSize);
  const bracketSlots: [number, number | null][] = [];
  for (let i = 0; i < order.length; i += 2) {
    const redSeed = order[i];
    const blueSeed = order[i + 1];
    if (redSeed <= competitorCount) {
      bracketSlots.push([
        redSeed,
        blueSeed <= competitorCount ? blueSeed : null,
      ]);
    } else if (blueSeed <= competitorCount) {
      bracketSlots.push([blueSeed, null]);
    }
  }

  return { bracketSlots, matchCount: bracketSize - 1 };
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

  const levelCount = numLevels(matches.length);

  while (allMatches.length && levels.length < levelCount) {
    const nextLevelMatches: Match[] = [];

    let removed = 0;

    for (const match of levels[levels.length - 1]) {
      const firstReferencedMatchIndex = allMatches.findIndex(m => referencesMatchRed(match, m));
      if (firstReferencedMatchIndex > -1) {
        nextLevelMatches.push(allMatches[firstReferencedMatchIndex]);
        allMatches.splice(firstReferencedMatchIndex, 1);
        removed++;
      } else if (matches.length > 4 && levels.length + 1 === numLevels(matches.length)) {
        nextLevelMatches.push(createBye(match.red_id, match.red_name, match.red_team, match.red_instagram_profile, match.red_personal_name, match.red_profile_image_url,
          match.red_country, match.red_country_note, match.red_country_note_pt,
          match.red_seed, match.red_ordinal, match.red_weight, match.red_rating, match.red_match_count, match.red_note, match.red_percentile, match.red_percentile_age));
      }
      const secondReferencedMatchIndex = allMatches.findIndex(m => referencesMatchBlue(match, m));
      if (secondReferencedMatchIndex > -1) {
        nextLevelMatches.push(allMatches[secondReferencedMatchIndex]);
        allMatches.splice(secondReferencedMatchIndex, 1);
        removed++;
      } else if (matches.length > 4 && levels.length + 1 === numLevels(matches.length)) {
          nextLevelMatches.push(createBye(match.blue_id, match.blue_name, match.blue_team, match.blue_instagram_profile, match.blue_personal_name, match.blue_profile_image_url,
            match.blue_country, match.blue_country_note, match.blue_country_note_pt,
            match.blue_seed, match.blue_ordinal, match.blue_weight, match.blue_rating, match.blue_match_count, match.blue_note, match.blue_percentile, match.blue_percentile_age));
      }
    }

    if (removed === 0) {
      break;
    }

    // not enough matches to fill the next level
    if (levels.length > 0 && nextLevelMatches.length < levels[levels.length - 1].length * 2) {
      break;
    }
    
    levels.push(nextLevelMatches);
  }

  return levels.reverse();
}
