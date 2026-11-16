import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import vm from 'node:vm';
import ts from 'typescript';

// Exercise the actual request coordinator with controlled HTTP responses.
function setup() {
  let handler;
  let configCalls = 0;
  let retries = 0;
  let postError;
  let adapter = async config => ({ config, data: { rows: [], totalPages: 1 } });
  let onVerify = () => {};
  let networkCalls = 0;
  const send = async config => {
    networkCalls++;
    try { return await adapter(config); }
    catch (error) { return handler(error); }
  };
  const client = {
    interceptors: { response: { use: (_success, failure) => { handler = failure; } } },
    request: async config => { retries++; return send(config); },
    get: async (url, config) => send({ ...config, url }),
  };
  const axios = {
    create: () => client,
    get: async () => { configCalls++; return { data: { enabled: true, siteKey: 'public' } }; },
    post: async () => { if (postError) throw postError; onVerify(); },
    isAxiosError: error => error?.isAxiosError === true,
  };
  const source = readFileSync(new URL('../src/matchAccess.ts', import.meta.url), 'utf8');
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  });
  const exports = {};
  vm.runInNewContext(outputText, { exports, require: () => axios });
  const error = (status = 403, code = 'match_access_required', config = {}) => ({
    isAxiosError: true, response: { status, data: { code } }, config,
  });
  return {
    access: exports,
    rejectRequest: (...args) => handler(...args),
    error,
    counts: () => ({ configCalls, retries, networkCalls }),
    setPostError: value => { postError = value; },
    setAdapter: value => { adapter = value; },
    setOnVerify: value => { onVerify = value; },
  };
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test('concurrent denied requests share verification and retry with original configuration', async () => {
  const s = setup();
  const config = { url: '/api/matches', params: { gi: 'true', page: 3 } };
  const first = s.rejectRequest(s.error(403, 'match_access_required', config));
  const second = s.rejectRequest(s.error());
  await flush();
  assert.equal(s.counts().configCalls, 1);
  assert.equal(s.access.getMatchAccessRequest().siteKey, 'public');
  await s.access.submitMatchAccessToken('token');
  const results = await Promise.all([first, second]);
  assert.equal(results[0].config.params.page, 3);
  assert.equal(s.counts().retries, 2);
  assert.equal(s.access.getMatchAccessRequest(), null);
});

test('429s, unrelated 403s, and a failed retry do not trigger a challenge loop', async () => {
  const s = setup();
  for (const error of [s.error(429, 'match_access_limited'), s.error(403, 'other'),
    s.error(403, 'match_access_required', { matchAccessRetried: true })]) {
    await assert.rejects(s.rejectRequest(error), value => value === error);
  }
  assert.equal(s.counts().configCalls, 0);
});

test('quota exhaustion renews once for concurrent requests and resumes browsing', async () => {
  const s = setup();
  const config = { url: '/api/matches', params: { gi: 'true', page: 17 } };
  const quotaError = s.error(403, 'match_access_required', config);
  quotaError.response.data.reason = 'quota_exhausted';
  const otherError = s.error();
  otherError.response.data.reason = 'quota_exhausted';
  const first = s.rejectRequest(quotaError);
  const second = s.rejectRequest(otherError);
  await flush();
  assert.equal(s.counts().configCalls, 1);
  assert.equal(s.counts().retries, 0);
  await s.access.submitMatchAccessToken('fresh-proof');
  const [response] = await Promise.all([first, second]);
  assert.equal(response.config.params.page, 17);
  assert.equal(s.counts().retries, 2);
  assert.equal(s.access.getMatchAccessRequest(), null);
  await assert.rejects(s.rejectRequest(quotaError), value => value === quotaError);
  assert.equal(s.counts().configCalls, 1);
});

test('failed token verification stays pending and can be retried', async () => {
  const s = setup();
  const request = s.rejectRequest(s.error());
  await flush();
  s.setPostError(new Error('Cloudflare unavailable'));
  await assert.rejects(s.access.submitMatchAccessToken('token'));
  assert.ok(s.access.getMatchAccessRequest());
  assert.equal(s.counts().retries, 0);
  s.setPostError(null);
  await s.access.submitMatchAccessToken('fresh-token');
  await request;
  assert.equal(s.counts().retries, 1);
});
test('cancelling clears verification and permits a later attempt', async () => {
  const s = setup();
  const request = s.rejectRequest(s.error());
  const rejected = assert.rejects(request, /cancelled/);
  await flush();
  s.access.cancelMatchAccess();
  await rejected;
  assert.equal(s.access.getMatchAccessRequest(), null);
  const next = s.rejectRequest(s.error());
  await flush();
  await s.access.submitMatchAccessToken('token');
  await next;
  assert.equal(s.counts().configCalls, 2);
});

test('queued comparison requests cannot exhaust a renewed session concurrently', async () => {
  const s = setup();
  let remaining = 24;
  s.setAdapter(async config => {
    if (remaining < 12) throw s.error(403, 'match_access_required', config);
    remaining -= 12;
    return { config, data: { rows: [], totalPages: 1 } };
  });
  s.setOnVerify(() => { remaining = 24; });
  const requests = Array.from({ length: 4 }, (_, page) => s.access.matchesApi.get('/api/matches', {
    params: { athlete_name: 'First', athlete_name2: 'Second', gi: 'true', page: page + 1 },
  }));
  await flush();
  // The fourth request waits for the third's verification and successful retry.
  assert.equal(s.counts().networkCalls, 3);
  assert.equal(s.counts().configCalls, 1);
  await s.access.submitMatchAccessToken('fresh-proof');
  const responses = await Promise.all(requests);
  assert.deepEqual(responses.map(response => response.config.params.page), [1, 2, 3, 4]);
  assert.equal(s.counts().configCalls, 1);
  assert.equal(s.counts().retries, 1);
});
