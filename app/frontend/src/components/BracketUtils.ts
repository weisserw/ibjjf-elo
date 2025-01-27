import axios, { type AxiosError } from 'axios'

export interface Competitor {
  ordinal: number
  id: string | null
  ibjjf_id: string | null
  seed: number
  name: string
  team: string
  rating: number | null
  rank: number | null
}

export interface CompetitorsResponse {
  error?: string
  competitors?: Competitor[]
}

export const isGi = (name: string) => {
  return !/no[ -]gi/.test(name.toLowerCase())
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
