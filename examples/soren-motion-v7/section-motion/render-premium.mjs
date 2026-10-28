import {bundle} from '@remotion/bundler';
import {getCompositions,renderStill,renderMedia} from '@remotion/renderer';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=path.dirname(fileURLToPath(import.meta.url));
const serveUrl=await bundle({entryPoint:path.join(root,'src/index.ts')});
const chromeOptions={gl:'angle'};
const all=(await getCompositions(serveUrl,{chromeOptions})).filter(c=>c.id.endsWith('Premium'));
const only=process.argv.find(a=>a.startsWith('--only='))?.split('=')[1];
const compositions=only?all.filter(c=>c.id.toLowerCase().startsWith(only)):all;
if(all.length!==4||compositions.length===0)throw new Error('Expected the four approved premium film concepts');
for(const composition of compositions){
 const name=composition.id.replace('Premium','').toLowerCase(),folder=path.join(root,'../resume-films-v7',name);
 await renderStill({serveUrl,composition,frame:60,chromeOptions,output:path.join(folder,'poster.png')});
 console.log('Reviewed still ready: '+name);
 if(process.argv.includes('--render')){
  await renderMedia({serveUrl,composition,codec:'h264',crf:19,concurrency:2,chromeOptions,outputLocation:path.join(folder,'film.mp4')});
  console.log('Rendered premium film: '+name);
 }
}
