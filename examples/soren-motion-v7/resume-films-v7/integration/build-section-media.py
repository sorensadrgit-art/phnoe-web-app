from pathlib import Path
import base64, hashlib, json, re, shutil, sys

ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'outputs'
VERSION=sys.argv[1] if len(sys.argv)>1 else 'v5'
assert VERSION in ('v5','v6','v7')
MEDIA=OUT/('resume-films-'+VERSION if VERSION!='v5' else 'resume-artifacts')
PROJECT=Path(r'C:\Users\soren\AppData\Roaming\Open Design\namespaces\release-stable-win\data\projects\4202b180-caa3-4ef1-95c4-2c3114917b4a')
BASE=OUT/'SOREN-Living-Resume-Reference-Motion-v4.html'
NAME='SOREN-Living-Resume-Premium-Films-v7.html' if VERSION=='v7' else 'SOREN-Living-Resume-Distinct-Films-v6.html' if VERSION=='v6' else 'SOREN-Living-Resume-Motion-Studies-v5.html'
source=BASE.read_bytes()
assert hashlib.sha256(source).hexdigest()=='304e810d183f51aaa573f541048a1666924245044400facbcdd29c05896e2e36'
html=source.decode('utf-8')
ids=['about','experience','education','projects','skills','contact']
videos={key:'data:video/mp4;base64,'+base64.b64encode((MEDIA/key/'film.mp4' if VERSION!='v5' else MEDIA/(key+'.mp4')).read_bytes()).decode() for key in ids}
posters={key:'data:image/png;base64,'+base64.b64encode((MEDIA/key/'poster.png' if VERSION!='v5' else MEDIA/(key+'.png')).read_bytes()).decode() for key in ids}
for key in ids:
    pattern=r'(id:"'+key+r'",number:.*?,image:")data:image/[^\"]+("[,}])'
    html,count=re.subn(pattern,lambda m:m[1]+posters[key]+m[2],html,count=1)
    assert count==1,key

def change(before,after):
    global html
    assert html.count(before)==1,(before[:110],html.count(before))
    html=html.replace(before,after,1)

runtime=(ROOT/'work/section-media-runtime.js').read_text(encoding='utf-8')
runtime='const SECTION_VIDEOS='+json.dumps(videos,separators=(',',':'))+';\n'+runtime
html=html.replace('<script type="module">','<script type="module">\n'+runtime+'\n',1)
if VERSION!='v5':
    start=html.index('function TU(l,t){');end=html.index('class bU{',start)
    html=html[:start]+'''function TU(l,t,target){const c=target||document.createElement('canvas');if(c.width!==ei||c.height!==Yi){c.width=ei;c.height=Yi}const x=c.getContext('2d');if(!x)throw new Error('2D canvas unavailable');x.fillStyle='#e9e5dc';x.fillRect(0,0,ei,Yi);if(t)x.drawImage(t,0,0,ei,Yi);const label=l.number+' / '+l.title;x.font='600 18px Arial';const w=x.measureText(label).width+28;x.fillStyle='rgba(241,238,232,.94)';x.beginPath();x.roundRect(24,14,w,29,14);x.fill();x.fillStyle='#242625';x.textBaseline='middle';x.fillText(label,38,29);return c}'''+html[end:]
else:
    change('function TU(l,t){const i=document.createElement("canvas");','function TU(l,t,target){const i=target||document.createElement("canvas");')
    change('ei/t.naturalWidth,h/t.naturalHeight),m=t.naturalWidth*p,_=t.naturalHeight*p',
           'ei/(t.videoWidth||t.naturalWidth),h/(t.videoHeight||t.naturalHeight)),m=(t.videoWidth||t.naturalWidth)*p,_=(t.videoHeight||t.naturalHeight)*p')
change('this.canvas.dataset.cardCount=String(this.sections.length)',
       'this.sectionMedia=new SectionMedia(this,TU),this.canvas.dataset.cardCount=String(this.sections.length)')
change('u.face.visible=!0,u.face.position.set(',
       'u.face.userData.mediaVisible=m.right>0&&m.left<window.innerWidth,u.face.visible=!0,u.face.position.set(')
change('this.renderer.render(this.scene,this.camera),t<Math.max(this.activeUntil,(this.introStarted||0)+2800)',
       'this.sectionMedia?.update(t);this.renderer.render(this.scene,this.camera),(this.sectionMedia?.playing||t<Math.max(this.activeUntil,(this.introStarted||0)+2800))')
change('this.disposed=!0,window.removeEventListener("resize",this.onResize)',
       'this.disposed=!0,this.sectionMedia?.dispose(),window.removeEventListener("resize",this.onResize)')
change('children:At.jsx("img",{src:G.image,alt:""})',
       'children:At.jsx(SectionVideo,{section:G})')
change('function XA(config){return referenceTrack(ce,config)}',
       'function SectionVideo({section}){const ref=ce.useRef(null);ce.useEffect(()=>bindSectionVideo(ref.current,section.id),[section.id]);return At.jsx("video",{ref,poster:section.image,muted:!0,loop:!0,playsInline:!0,preload:"none","aria-hidden":"true","data-section-video":section.id})}function XA(config){return referenceTrack(ce,config)}')
html=html.replace('</head>','<style>.sr-detail-photo video{width:100%;height:100%;object-fit:cover}.sr-detail-photo.is-hiker video{object-position:center}@media(min-width:721px){.sr-app{overflow:clip!important}}@media(prefers-reduced-motion:reduce){.sr-detail-photo video{object-fit:cover}}</style></head>')
if VERSION!='v5':
    html=html.replace('</head>','<style>.sr-card-art{inset:0!important;height:100%!important;opacity:1!important}.sr-card-art:before,.sr-card-art:after{display:none!important}.sr-card-top,.sr-card-copy{visibility:hidden!important}.sr-detail-photo{background:#171717!important}.sr-detail-photo video{object-fit:contain!important}</style></head>')
    colors={'about':'#e9e5dc','experience':'#191919','education':'#f4ecd9','projects':'#091421','skills':'#d7b9f0','contact':'#f2d798'}
    css=''.join(f'.sr-detail[data-open-section="{key}"] .sr-detail-photo{{background:{color}!important}}' for key,color in colors.items())
    html=html.replace('</head>','<style>'+css+'</style></head>')
html=html.replace('SOREN — A Living Résumé','SOREN — Motion Exhibits' if VERSION=='v7' else 'SOREN — Six Independent Films' if VERSION=='v6' else 'SOREN — Living Motion Studies')
for folder in (OUT,PROJECT):
    (folder/NAME).write_text(html,encoding='utf-8')
manifest={'version':1,'kind':'html','title':'SOREN — Premium Films v7' if VERSION=='v7' else 'SOREN — Distinct Films v6' if VERSION=='v6' else 'SOREN — Motion Studies v5','entry':NAME,'renderer':'html','status':'complete','exports':['html','zip']}
(PROJECT/(NAME+'.artifact.json')).write_text(json.dumps(manifest,indent=2),encoding='utf-8')
assert BASE.read_bytes()==source
if VERSION=='v5':shutil.copyfile(OUT/'section-motion/DESIGN.md',MEDIA/'DESIGN.md')
clips=[]
tweens=[]
for i,key in enumerate(ids):
    start=i*(7.5 if VERSION!='v5' else 5.5)
    src=key+'/film.mp4' if VERSION!='v5' else key+'.mp4'
    duration=8 if VERSION!='v5' else 6
    clips.append(f'<video id="{key}" class="clip" data-start="{start}" data-duration="{duration}" data-track-index="{i}" src="{src}" muted playsinline aria-label="{key} motion study"></video>')
    tweens.append(f'tl.from("#{key}",{{opacity:{.96 if i==0 else 0},duration:.5,ease:"{["power2.out","sine.out","power3.out"][i%3]}"}},{start+.15 if i==0 else start});')
composition='''<!doctype html><html lang="en"><head><meta charset="utf-8"><title>SOREN — Six Motion Studies</title><style>html,body{margin:0;background:#10282b} [data-composition-id]{position:relative;width:1200px;height:704px;overflow:hidden;background:#10282b}.clip{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}</style></head><body><div id="resume-studies" data-composition-id="resume-studies" data-width="1200" data-height="704" data-start="0" data-duration="33.5">'''+''.join(clips)+'''</div><script src="gsap.min.js"></script><script>window.__timelines=window.__timelines||{};const tl=gsap.timeline({paused:true});'''+''.join(tweens)+'''window.__timelines['resume-studies']=tl;</script></body></html>'''
(MEDIA/'index.html').write_text(composition,encoding='utf-8')
if VERSION!='v5':
    composition=composition.replace('data-duration="33.5"','data-duration="45.5"').replace('SOREN — Six Motion Studies','SOREN — Six Distinct Films')
    (MEDIA/'index.html').write_text(composition,encoding='utf-8')
    cards=''.join(f'<article><h2>{key.title()}</h2><video src="{key}/film.mp4" poster="{key}/poster.png" controls muted loop playsinline preload="none"></video></article>' for key in ids)
    (MEDIA/'gallery.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>SOREN — Six Independent Films</title><style>body{margin:0;background:#eee9df;color:#252525;font:18px Arial;padding:40px}h1{font:48px Georgia;margin:0}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:30px;margin-top:30px}h2{font:20px Arial}video{width:100%;display:block;border-radius:14px;background:#191919}p{max-width:800px;line-height:1.5}</style><h1>Six films. Six directions.</h1><p>Original motion pieces for Soren Sadr. Every section has a separate editable HyperFrames project. Play each film independently.</p><main>'+cards+'</main></html>',encoding='utf-8')
gsap=PROJECT/'node_modules/gsap/dist/gsap.min.js'
shutil.copyfile(gsap,MEDIA/'gsap.min.js')
print(json.dumps({'entry':str(OUT/NAME),'bytes':len(html.encode()),'sections':ids,'v4Preserved':True}))
