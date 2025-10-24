import { toast } from 'bulma-toast';
import { countryNames, countryNamesPt } from './countries';

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

export const ages = [
  'Juvenile',
  'Adult',
  'Master 1',
  'Master 2',
  'Master 3',
  'Master 4',
  'Master 5',
  'Master 6',
  'Master 7',
]

export interface DBRow {
  id: string
  winner: string
  winnerId: string
  winnerStartRating: number
  winnerEndRating: number
  winnerWeightForOpen: string | null
  winnerRatingNote: string | null
  winnerStartMatchCount: number
  winnerEndMatchCount: number
  winnerInstagramProfile: string | null
  winnerInstagramProfilePersonalName: string | null
  winnerProfileImageUrl: string | null
  winnerCountry: string | null
  winnerCountryNote: string | null
  winnerCountryNotePt: string | null
  loser: string
  loserId: string
  loserStartRating: number
  loserEndRating: number
  loserWeightForOpen: string | null
  loserRatingNote: string | null
  loserStartMatchCount: number
  loserEndMatchCount: number
  loserInstagramProfile: string | null
  loserInstagramProfilePersonalName: string | null
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
}

export interface DBResults {
  rows: DBRow[]
  totalPages: number
}

export const isHistorical = (eventName: string) => {
  return !/idade 04 a 15 anos/.test(eventName) && /\([^\)]+\)/.test(eventName);
}

export const noMatchStrings = [
  "disqualified by no show",
  "desqualificado por no show",
  "disqualified by overweight",
  "disqualified by acima do peso",
  "disqualified by withdraw",
  "desqualificado por retirada",
];

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