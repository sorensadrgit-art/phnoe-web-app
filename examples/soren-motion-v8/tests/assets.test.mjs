import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
import test from 'node:test';
const root=new URL('../',import.meta.url);
const read=path=>readFileSync(new URL(path,root));

test('v8 uses the unchanged v7 reference controller',()=>{
  const baseline=JSON.parse(read('baseline.json'));
  assert.equal(createHash('sha256').update(read('src/resume/reference-motion.mjs')).digest('hex'),baseline.referenceMotionSha256);
});
test('all six films and posters ship locally',()=>{
  for(const id of ['about','experience','education','projects','skills','contact']){
    assert.ok(read('public/media/'+id+'-film.mp4').length>10000);
    assert.equal(read('public/media/'+id+'-poster.png').subarray(1,4).toString(),'PNG');
  }
});
test('anatomy asset contains actual bone muscle and tendon meshes',()=>{
  const buffer=read('public/models/anatomy-low.glb');
  assert.equal(buffer.subarray(0,4).toString(),'glTF');
  assert.equal(buffer.readUInt32LE(4),2);
  const data=JSON.parse(buffer.subarray(20,20+buffer.readUInt32LE(12)).toString());
  for(const layer of ['bone','muscle','tendon'])assert.ok(data.nodes.some(n=>n.mesh!==undefined&&n.name.startsWith(layer)));
});
test('demo export has finite 3D coordinates and valid bone references',()=>{
  const data=JSON.parse(read('public/models/demo.motion.json'));
  assert.equal(data.schema,'kinelab.motion.v1');
  assert.ok(data.fps>0&&data.frames.length>1);
  const count=data.markers.length;
  for(const frame of data.frames){assert.equal(frame.xyz.length,count);assert.ok(frame.xyz.every(p=>p.length===3&&p.every(Number.isFinite)));}
  for(const bone of data.bones)assert.ok(bone.length===2&&bone.every(i=>Number.isInteger(i)&&i>=0&&i<count));
  assert.ok(data.frames.every((frame,i)=>i===0||frame.t>=data.frames[i-1].t));
});
test('portable build includes local assets and relative entry paths',()=>{
  if(!existsSync(new URL('dist/index.html',root)))throw Error('Run npm run build before npm test.');
  const html=read('dist/index.html').toString();
  assert.ok(html.includes('./assets/'));
  for(const file of ['models/anatomy-low.glb','models/demo.motion.json','media/about-film.mp4']){
    assert.deepEqual(read('dist/'+file),read('public/'+file));
  }
});
