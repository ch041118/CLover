import test from 'node:test';
import assert from 'node:assert/strict';
import { ApiClient, ApiError, resolveBaseUrl } from '../src/api.ts';

test('production requires HTTPS even when development exception is configured', () => {
  assert.throws(() => resolveBaseUrl('http://192.168.0.10:8000', false, true));
  assert.equal(resolveBaseUrl('https://care.example.org/', false, false), 'https://care.example.org');
});
test('HTTP is explicit and private development only', () => {
  for (const host of ['192.168.0.10', '10.0.0.4', '172.16.0.2', 'localhost']) {
    assert.equal(resolveBaseUrl(`http://${host}:8000`, true, true), `http://${host}:8000`);
    assert.throws(() => resolveBaseUrl(`http://${host}:8000`, true, false));
  }
  assert.throws(() => resolveBaseUrl('http://example.org', true, true));
  assert.throws(() => resolveBaseUrl('http://172.32.0.1', true, true));
});
test('URL rejects credentials, paths, query strings and fragments', () => {
  for (const value of [undefined, 'oops', 'https://user:pass@care.example.org', 'https://care.example.org/api', 'https://care.example.org?token=x', 'https://care.example.org#x']) {
    assert.throws(() => resolveBaseUrl(value, false, false));
  }
});
test('care submission uses only configured API with no redirects or persistent cache', async () => {
  const calls = [];
  const api = new ApiClient('https://care.example.org', () => {}, async (url, options) => {
    calls.push({ url, options }); return Response.json({ id: 'test' }, { status: 201 });
  });
  api.token = 'test-token';
  const body = { note: '가상 식사 요청', allow_local_ai: false };
  assert.deepEqual(await api.request('/api/care-requests', body), { id: 'test' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, 'https://care.example.org/api/care-requests');
  assert.equal(calls[0].options.redirect, 'error');
  assert.equal(calls[0].options.cache, 'no-store');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer test-token');
  assert.deepEqual(JSON.parse(calls[0].options.body), body);
});
test('expired authenticated session clears token and prevents further calls', async () => {
  let expired = 0, calls = 0;
  const api = new ApiClient('https://care.example.org', () => expired++, async () => {
    calls++; return new Response('private server details', { status: 401 });
  });
  api.token = 'test-token';
  await assert.rejects(api.request('/api/me'), ApiError);
  assert.equal(api.token, ''); assert.equal(expired, 1);
  await assert.rejects(api.request('/api/me'), ApiError);
  assert.equal(calls, 1);
});
test('failed login does not close unauthenticated client', async () => {
  const api = new ApiClient('https://care.example.org', () => assert.fail(), async () => new Response('', { status: 401 }));
  await assert.rejects(api.request('/api/login', {}), ApiError);
  assert.equal(api.closed, false);
});
test('network failure is not automatically retried and does not expose response text', async () => {
  let calls = 0;
  const api = new ApiClient('https://care.example.org', () => {}, async () => { calls++; throw new Error('secret'); });
  await assert.rejects(api.request('/api/care-requests', {}), error => error.status === 0 && !error.message.includes('secret'));
  assert.equal(calls, 1);
});
test('logout aborts in-flight requests and discards late responses', async () => {
  let finish, signal;
  const api = new ApiClient('https://care.example.org', () => {}, async (_, options) => {
    signal = options.signal; return new Promise(resolve => { finish = resolve; });
  });
  api.token = 'test-token';
  const pending = api.request('/api/me');
  api.close(); assert.equal(signal.aborted, true);
  finish(Response.json({ id: 'private' }));
  await assert.rejects(pending, ApiError);
});
test('logout while response body is being read discards user data', async () => {
  let finish;
  const api = new ApiClient('https://care.example.org', () => {}, async () => ({ ok: true, json: () => new Promise(resolve => { finish = resolve; }) }));
  const pending = api.request('/api/me');
  await new Promise(resolve => setImmediate(resolve));
  api.close(); finish({ id: 'private' });
  await assert.rejects(pending, ApiError);
});

test('location failures explain search configuration and schedule restrictions without exposing server text',async()=>{
  const api=new ApiClient('https://example.com',()=>{},async()=>new Response(JSON.stringify({detail:'private server data'}),{status:409}));
  await assert.rejects(api.request('/api/location/search',{query:'테스트로',consent:true}), /주소 검색 서비스/);
  await assert.rejects(api.request('/api/location',{}), /일정/);
});
