import axios, { type AxiosRequestConfig, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';

type AccessRequest = { siteKey: string };
let request: AccessRequest | null = null;
let pending: Promise<void> | null = null;
let complete: (() => void) | null = null;
let cancel: ((error: Error) => void) | null = null;
const listeners = new Set<() => void>();

export const subscribeMatchAccess = (listener: () => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
export const getMatchAccessRequest = () => request;

function publish(next: AccessRequest | null) {
  request = next;
  listeners.forEach(listener => listener());
}

function ensureMatchAccess(): Promise<void> {
  if (pending) return pending;
  pending = axios.get<{ enabled: boolean; siteKey: string }>('/api/access/config', { timeout: 10000 })
    .then(({ data }) => {
      if (!data.enabled) return;
      if (!data.siteKey) throw new Error('Match verification is unavailable.');
      return new Promise<void>((resolve, reject) => {
        complete = resolve;
        cancel = reject;
        publish({ siteKey: data.siteKey });
      });
    })
    .finally(() => {
      complete = null;
      cancel = null;
      publish(null);
      pending = null;
    });
  return pending;
}

export async function submitMatchAccessToken(token: string) {
  await axios.post('/api/access/verify', { token }, { timeout: 15000 });
  complete?.();
}

export function cancelMatchAccess() {
  cancel?.(new Error('Match verification cancelled. Please reload to try again.'));
}

// Use a separate client so unrelated APIs never trigger verification. Concurrent
// missing, expired, or quota-exhausted sessions share one challenge, and each
// original request retries once. Burst-limit 429s never renew the allowance.
const client = axios.create();
client.interceptors.response.use(response => response, async (error: unknown) => {
  if (!axios.isAxiosError(error)) throw error;
  const config = error.config as (InternalAxiosRequestConfig & { matchAccessRetried?: boolean }) | undefined;
  if (error.response?.status !== 403
      || error.response.data?.code !== 'match_access_required'
      || !config || config.matchAccessRetried) {
    throw error;
  }
  config.matchAccessRetried = true;
  await ensureMatchAccess();
  return client.request(config);
});

// Keep requests queued through verification and the retry. Otherwise multiple
// requests can immediately exhaust a session that is close to its quota.
let queue: Promise<void> = Promise.resolve();
export const matchesApi = {
  get<T>(url: string, config?: AxiosRequestConfig): Promise<AxiosResponse<T>> {
    const result = queue.then(() => client.get<T>(url, config));
    queue = result.then(() => undefined, () => undefined);
    return result;
  },
};
