import { toast } from 'bulma-toast';

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


const countryFlagEmoji: Record<string, string> = {
  'ae': '🇦🇪',
  'ao': '🇦🇴',
  'ar': '🇦🇷',
  'au': '🇦🇺',
  'be': '🇧🇪',
  'br': '🇧🇷',
  'ca': '🇨🇦',
  'cn': '🇨🇳',
  'cr': '🇨🇷',
  'de': '🇩🇪',
  'ee': '🇪🇪',
  'es': '🇪🇸',
  'fl': '🇫🇮',
  'fr': '🇫🇷',
  'gb': '🇬🇧',
  'hu': '🇭🇺',
  'ie': '🇮🇪',
  'is': '🇮🇸',
  'it': '🇮🇹',
  'jp': '🇯🇵',
  'kg': '🇰🇬',
  'kr': '🇰🇷',
  'kz': '🇰🇿',
  'ma': '🇲🇦',
  'md': '🇲🇩',
  'mx': '🇲🇽',
  'no': '🇳🇴',
  'pe': '🇵🇪',
  'pl': '🇵🇱',
  'pt': '🇵🇹',
  'ro': '🇷🇴',
  'ru': '🇷🇺',
  'sa': '🇸🇦',
  'se': '🇸🇪',
  'tt': '🇹🇹',
  'ua': '🇺🇦',
  'uk': '🇬🇧',
  'us': '🇺🇸',
};

const countryNames: Record<string, string> = {
  'ae': 'United Arab Emirates',
  'ao': 'Angola',
  'ar': 'Argentina',
  'au': 'Australia',
  'be': 'Belgium',
  'br': 'Brazil',
  'ca': 'Canada',
  'cn': 'China',
  'cr': 'Costa Rica',
  'de': 'Germany',
  'ee': 'Estonia',
  'es': 'Spain',
  'fl': 'Finland',
  'fr': 'France',
  'gb': 'United Kingdom',
  'hu': 'Hungary',
  'ie': 'Ireland',
  'is': 'Iceland',
  'it': 'Italy',
  'jp': 'Japan',
  'kg': 'Kyrgyzstan',
  'kr': 'South Korea',
  'kz': 'Kazakhstan',
  'ma': 'Morocco',
  'md': 'Moldova',
  'mx': 'Mexico',
  'no': 'Norway',
  'pe': 'Peru',
  'pl': 'Poland',
  'pt': 'Portugal',
  'ro': 'Romania',
  'ru': 'Russia',
  'sa': 'Saudi Arabia',
  'se': 'Sweden',
  'tt': 'Trinidad and Tobago',
  'ua': 'Ukraine',
  'uk': 'United Kingdom',
  'us': 'United States',
};

const countryNamesPt: Record<string, string> = {
  'ae': 'Emirados Árabes Unidos',
  'ao': 'Angola',
  'ar': 'Argentina',
  'au': 'Austrália',
  'be': 'Bélgica',
  'br': 'Brasil',
  'ca': 'Canadá',
  'cn': 'China',
  'cr': 'Costa Rica',
  'de': 'Alemanha',
  'ee': 'Estônia',
  'es': 'Espanha',
  'fl': 'Finlândia',
  'fr': 'França',
  'gb': 'Reino Unido',
  'hu': 'Hungria',
  'ie': 'Irlanda',
  'is': 'Islândia',
  'it': 'Itália',
  'jp': 'Japão',
  'kg': 'Quirguistão',
  'kr': 'Coreia do Sul',
  'kz': 'Cazaquistão',
  'ma': 'Marrocos',
  'md': 'Moldávia',
  'mx': 'México',
  'no': 'Noruega',
  'pe': 'Peru',
  'pl': 'Polônia',
  'pt': 'Portugal',
  'ro': 'Romênia',
  'ru': 'Rússia',
  'sa': 'Arábia Saudita',
  'se': 'Suécia',
  'tt': 'Trinidad e Tobago',
  'ua': 'Ucrânia',
  'uk': 'Reino Unido',
  'us': 'Estados Unidos',
};

export function getFlagEmoji(country: string | null): string | null {
  if (!country) return null;
  const key = country.trim().toLowerCase().substring(0, 2);
  return countryFlagEmoji[key] || key;
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