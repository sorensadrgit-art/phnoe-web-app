import {test} from 'node:test';
import assert from 'node:assert/strict';
import {existsSync} from 'node:fs';
import {validateObservation} from './recordingClient.js';

test('pinned synthetic generator produces explicit valid raw observations for all protocols', async()=>{
 assert.ok(existsSync(new URL('./syntheticPose.js',import.meta.url)), 'standalone synthetic generator required');
 const {generateSimulatedPose}=await import('./syntheticPose.js');
 for(const type of ['squats','lunges','knee-extension','balance']){
  for(let step=0;step<120;step++){
   const points=generateSimulatedPose(step,type);
   assert.equal(points.length,33);
   const landmarks=points.map(p=>p?[p.x,p.y,p.z,p.visibility]:null);
   validateObservation({time_ms:step*33,landmarks,valid:true,reasons:[]});
  }
 }
});
