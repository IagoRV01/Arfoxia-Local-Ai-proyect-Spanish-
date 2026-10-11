import assert from 'node:assert/strict';
import test from 'node:test';
import { taskActive, waitForWorkTask, type WorkTask } from '../src/workTasks';
import type { ChatResponse } from '../src/types';

const initial: WorkTask = {id:'one-job', conversation_id:'one-chat',status:'running',rounds:0,calls:0,last_action:'model'};
const result = {message:'Completado',model:'local',model_mode:'dual'} as ChatResponse;
test('polls same task past six rounds, without another submission', async () => {
  let count=0;
  const ids:string[]=[];
  const response=await waitForWorkTask(initial,async id => {
    ids.push(id); count++;
    return {...initial,rounds:count,status:count>8?'completed':'running',result:count>8?result:undefined};
  },undefined,async()=>{});
  assert.equal(response,result); assert.equal(count,9);
  assert.ok(ids.every(id=>id==='one-job'));
});
test('fast completion resolves the stored result via GET', async()=>{
  assert.equal(await waitForWorkTask({...initial,status:'completed'},async()=>({...initial,status:'completed',result}),undefined,async()=>{}),result);
});
test('a lost connection is not retried as a new task', async()=>{
  let calls=0;
  await assert.rejects(waitForWorkTask(initial,async()=>{calls++;throw new Error('offline')},undefined,async()=>{}),/offline/);
  assert.equal(calls,1);
});
test('cancel/interrupted states do not wait or replay actions', async()=>{
  assert.ok(!taskActive({...initial,status:'interrupted'}));
  await assert.rejects(waitForWorkTask({...initial,status:'cancelled'},async()=>({...initial,status:'cancelled',message:'Detenido'})),/Detenido/);
});
