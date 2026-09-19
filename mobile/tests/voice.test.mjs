import test from 'node:test';
import assert from 'node:assert/strict';
import { voiceDecision } from '../src/voice.ts';
test('only explicit confirmation submits voice draft',()=>{
  assert.equal(voiceDecision('접수해 주세요.'),'submit');
  for(const text of ['접수하지 마세요','아니 접수해 주세요','접수해 주세요라는 말','네','', '취소하고 접수해줘'])assert.equal(voiceDecision(text),'unknown');
});
test('cancellation is unambiguous',()=>{
  assert.equal(voiceDecision('취소해 주세요!'),'cancel');
  assert.equal(voiceDecision('아니요'),'cancel');
});
