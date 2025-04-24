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
  loser: string
  loserId: string
  loserStartRating: number
  loserEndRating: number
  loserWeightForOpen: string | null
  loserRatingNote: string | null
  loserStartMatchCount: number
  loserEndMatchCount: number
  event: string
  age: string
  gender: string
  belt: string
  weight: string
  date: string
  rated: boolean
  notes: string
}

export interface DBResults {
  rows: DBRow[]
  totalPages: number
}

export const isHistorical = (row: DBRow) => {
  return /\([^\)]+\)/.test(row.event);
}
