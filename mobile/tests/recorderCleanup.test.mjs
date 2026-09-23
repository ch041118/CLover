import test from 'node:test';
import assert from 'node:assert/strict';
import { stopAndCleanRecorder } from '../src/recorderCleanup.ts';

test('cleanup resolves even when released native getter and stop throw synchronously', async () => {
  const recorder = { get uri() { throw Error('shared object already released'); }, stop() { throw Error('shared object already released'); } };
  await assert.doesNotReject(stopAndCleanRecorder(recorder, () => {}));
});
test('release while stopping still removes the captured recording file', async () => {
  let released = false;
  const removed = [];
  const recorder = { get uri() { if (released) throw Error('released'); return 'file://recording.m4a'; }, async stop() { released = true; throw Error('released during stop'); } };
  await stopAndCleanRecorder(recorder, uri => removed.push(uri));
  assert.deepEqual(removed, ['file://recording.m4a']);
});
test('overlapping background and unmount cleanup stops once and later sessions can stop again', async () => {
  let finish, calls = 0;
  const recorder = { uri: 'file://recording.m4a', stop() { calls++; return new Promise(resolve => { finish = resolve; }); } };
  const a = stopAndCleanRecorder(recorder, () => {});
  const b = stopAndCleanRecorder(recorder, () => {});
  assert.equal(a, b); assert.equal(calls, 1);
  finish(); await a;
  const c = stopAndCleanRecorder(recorder, () => {});
  assert.equal(calls, 2); finish(); await c;
});
test('cache deletion failure cannot escape as an unhandled rejection', async () => {
  await assert.doesNotReject(stopAndCleanRecorder({ uri: 'file://a', async stop() {} }, () => { throw Error('file unavailable'); }));
});
