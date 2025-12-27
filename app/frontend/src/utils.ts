import dayjs from 'dayjs';
import { toast } from 'bulma-toast';
import { countryNames, countryNamesPt } from './countries';
import eliteTier1Badge from '/src/assets/elite-tier1.png';
import eliteTier2Badge from '/src/assets/elite-tier2.png';
import eliteTier3Badge from '/src/assets/elite-tier3.png';

const showToast = (message: string) => {
  toast({
    message,
    type: 'is-danger',
    dismissible: true,
    pauseOnHover: true,
    duration: 5000,
    single: true,
  });
}

export const axiosErrorToast = (error: any) => {
  if (error.response && error.response.data.error) {
    showToast(`Error: ${error.response.data.error}`);
  } else if (error.response) {
    showToast(`Error: ${error.response.status} - ${error.response.statusText}`);
  } else if (error.request) {
    showToast('Error: No response received from server');
  } else {
    showToast(`Error: ${error.message}`);
  }
}

export const immatureClass = (matchCount: number | null) => {
  if (matchCount === null) {
    return ''
  }
  if (matchCount <= 4) {
    return 'very-immature'
  } else if (matchCount <= 6) {
    return 'immature'
  } else {
    return ''
  }
}


export interface DBRow {
  id: string
  winner: string
  winnerSlug: string
  winnerId: string
  winnerStartRating: number
  winnerEndRating: number
  winnerWeightForOpen: string | null
  winnerRatingNote: string | null
  winnerStartMatchCount: number
  winnerEndMatchCount: number
  winnerInstagramProfile: string | null
  winnerPersonalName: string | null
  winnerProfileImageUrl: string | null
  winnerCountry: string | null
  winnerCountryNote: string | null
  winnerCountryNotePt: string | null
  loser: string
  loserSlug: string
  loserId: string
  loserStartRating: number
  loserEndRating: number
  loserWeightForOpen: string | null
  loserRatingNote: string | null
  loserStartMatchCount: number
  loserEndMatchCount: number
  loserInstagramProfile: string | null
  loserPersonalName: string | null
  loserProfileImageUrl: string | null
  loserCountry: string | null
  loserCountryNote: string | null
  loserCountryNotePt: string | null
  event: string
  age: string
  gender: string
  belt: string
  weight: string
  date: string
  rated: boolean
  notes: string
  matchLocation: string | null
  videoLink: string | null
}

export interface DBResults {
  rows: DBRow[]
  totalPages: number
}

export interface Registration {
  event_name: string
  event_id: string
  division: string
  event_start_date: string
  event_end_date: string
  link: string
}

export interface AthleteSuggestion {
  name: string;
  personal_name: string | null;
}

export function renderAthleteSuggestion(suggestion: AthleteSuggestion): string {
  if (suggestion.personal_name) {
    return `${suggestion.personal_name} (${suggestion.name})`;
  }
  return suggestion.name;
}

export function formatEventDates(startDate: string, endDate: string, language: string): string {
    if (!startDate || !endDate) {
        return "";
    }
    const start = dayjs(startDate);
    const end = dayjs(endDate);

    if (!start.isValid() || !end.isValid()) {
        return "";
    }

    if (start.isSame(end, 'day')) {
        // Example: Oct 15
        return `${start.locale(language).format('MMM')} ${start.date()}`;
    }
    if (start.month() === end.month() && start.year() === end.year()) {
        // Example: Oct 15 - 17
        return `${start.locale(language).format('MMM')} ${start.date()} - ${end.date()}`;
    }
    // Example: Oct 28 - Nov 2
    return `${start.locale(language).format('MMM')} ${start.date()} - ${end.locale(language).format('MMM')} ${end.date()}`;
}

export const isHistorical = (eventName: string) => {
  return !/idade 04 a 15 anos/.test(eventName) && /\([^\)]+\)/.test(eventName);
}


export function getCountryName(country: string | null, note: string | null, note_pt: string | null, locale: string): string | undefined {
  if (!country) return undefined;
  const key = country.trim().toLowerCase().substring(0, 2);
  if (locale === 'pt') {
    const name = countryNamesPt[key] || country;
    if (note_pt) {
      return `${name} (${note_pt})`;
    } else {
      return name;
    }
  } else {
    const name = countryNames[key] || country;
    if (note) {
      return `${name} (${note})`;
    } else {
      return name;
    }
  }
}

export const percentileInteger = (percentile: number): number => {
  const inverted = (1 - percentile) * 100;

  if (inverted >= 99) {
    return parseFloat(inverted.toFixed(1));
  }

  return Math.round(inverted);
};

export const badgeForPercentile = (percentile: number | null, belt: string): [string | null, string] => {
  if (percentile === null) return [null, ''];

  if (!belt || ['WHITE', 'GREY', 'YELLOW', 'YELLOW-GREY', 'ORANGE', 'GREEN', 'GREEN-ORANGE'].includes(belt)) {
    return [null, ''];
  }

  const invertedPct = percentileInteger(percentile);

  if (invertedPct >= 98) {
    return [eliteTier1Badge, 'Tier 1 Elite (Top 2%)'];
  } else if (invertedPct >= 95) {
    return [eliteTier2Badge, 'Tier 2 Elite (Top 5%)'];
  } else if (invertedPct >= 90) {
    return [eliteTier3Badge, 'Tier 3 Elite (Top 10%)'];
  } else {
    return [null, ''];
  }
};