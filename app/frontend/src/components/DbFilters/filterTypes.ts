export interface FilterValues {
  athlete_name?: string;
  event_name?: string;
  gender_male?: boolean;
  gender_female?: boolean;
  age_adult?: boolean;
  age_master1?: boolean;
  age_master2?: boolean;
  age_master3?: boolean;
  age_master4?: boolean;
  age_master5?: boolean;
  age_master6?: boolean;
  age_master7?: boolean;
  age_juvenile?: boolean;
  age_teen?: boolean;
  belt_grey?: boolean;
  belt_yellow?: boolean;
  belt_orange?: boolean;
  belt_green?: boolean;
  belt_white?: boolean;
  belt_blue?: boolean;
  belt_purple?: boolean;
  belt_brown?: boolean;
  belt_black?: boolean;
  weight_rooster?: boolean;
  weight_light_feather?: boolean;
  weight_feather?: boolean;
  weight_light?: boolean;
  weight_middle?: boolean;
  weight_medium_heavy?: boolean;
  weight_heavy?: boolean;
  weight_super_heavy?: boolean;
  weight_ultra_heavy?: boolean;
  weight_open_class?: boolean;
  date_start?: string;
  date_end?: string;
  rating_start?: number;
  rating_end?: number;
}

export interface OpenFilters {
  athlete: boolean;
  event: boolean;
  division: boolean;
}

export type FilterKeys = keyof FilterValues;

export type DivisionFilterKeys = {
  [K in FilterKeys]: K extends `gender_${string}` | `age_${string}` | `belt_${string}` | `weight_${string}` ? K : never
}[FilterKeys];

export const ageToFilter = (age: string) => `age_${age.toLowerCase().replace(' ', '')}` as DivisionFilterKeys;
export const genderToFilter = (gender: string) => `gender_${gender.toLowerCase()}` as DivisionFilterKeys;
export const beltToFilter = (belt: string) => `belt_${belt.toLowerCase()}` as DivisionFilterKeys;
export const weightToFilter = (weight: string): DivisionFilterKeys => {
  if (weight === 'Open Class Light' || weight === 'Open Class Heavy') {
    return weightToFilter('Open Class');
  }
  return `weight_${weight.toLowerCase().replace(' ', '_')}` as DivisionFilterKeys;
}; 