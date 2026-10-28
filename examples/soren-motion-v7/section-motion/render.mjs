import {bundle} from '@remotion/bundler';
import {getCompositions, renderMedia, renderStill} from '@remotion/renderer';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const root=path.dirname(fileURLToPath(import.meta.url));
const serveUrl=await bundle({entryPoint:path.join(root,'src/index.ts')});
const compositions=(await getCompositions(serveUrl)).filter(c=>!c.id.endsWith('Premium'));
if(compositions.length!==6) throw new Error('Expected six section studies');
for(const composition of compositions){
 const name=composition.id.toLowerCase();
 await renderMedia({serveUrl,composition,codec:'h264',crf:20,concurrency:4,outputLocation:path.join(root,'../resume-artifacts',name+'.mp4')});
 await renderStill({serveUrl,composition,frame:45,output:path.join(root,'../resume-artifacts',name+'.png')});
 console.log('Rendered '+name);
}
