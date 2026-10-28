import json,pathlib,subprocess,re,time,sys
from check_motion import command
from probe_reference import evaluate
ROOT=pathlib.Path(__file__).resolve().parent.parent
VERSION=sys.argv[1] if len(sys.argv)>1 else 'v5'
assert VERSION in ('v5','v6','v7')
S='resume-motion-qa-'+VERSION if VERSION!='v5' else 'resume-motion-final-v5'
checks=[]
def state(js):return evaluate(js,S)
def settle(ms):state('(async()=>{await new Promise(r=>setTimeout(r,'+str(ms)+'));return true})()')
def check(name,passed):
    assert passed,name
    checks.append(name);print('PASS '+name,flush=True)

source=(ROOT/'outputs'/('SOREN-Living-Resume-Premium-Films-v7.html' if VERSION=='v7' else 'SOREN-Living-Resume-Distinct-Films-v6.html' if VERSION=='v6' else 'SOREN-Living-Resume-Motion-Studies-v5.html')).read_text(encoding='utf-8')
module=re.search(r'<script type="module">(.*?)</script>',source,re.S)[1]
temp=ROOT/'work/v5-check.mjs';temp.write_text(module,encoding='utf-8')
syntax=subprocess.run(['node','--check',str(temp)],capture_output=True,text=True,encoding='utf-8')
check('generated module parses',syntax.returncode==0)
command(S,'set','viewport','1440','900');settle(1400)
check('six motion studies initialized',state('document.querySelector("canvas[data-motion-studies]")?.dataset.motionStudies==="6"'))
before=state('Number(document.querySelector("canvas[data-motion-studies]").dataset.mediaFrames)');settle(500)
after=state('Number(document.querySelector("canvas[data-motion-studies]").dataset.mediaFrames)')
check('live video frames reach WebGL textures',after>before+4)
check('visible decoder count is bounded',state('Number(document.querySelector("canvas[data-motion-studies]").dataset.playingStudies)<=4'))
for key,title in [('about','ABOUT ME'),('experience','EXPERIENCE'),('education','EDUCATION'),('projects','PROJECTS'),('skills','SKILLS'),('contact','CONTACT')]:
    command(S,'click','button[aria-label="Open '+title+'"]');command(S,'snapshot','-i');settle(1200)
    check(key+' detail video plays',state('(()=>{const v=document.querySelector("video[data-section-video='+key+']");return !!v&&v.readyState>=2&&!v.paused&&v.currentTime>0})()'))
    command(S,'press','Escape');command(S,'snapshot','-i');settle(1050)
    check(key+' dialog closes',state('!document.querySelector(".sr-detail")'))
command(S,'set','media','dark','reduced-motion');settle(350)
check('reduced motion stops WebGL',state('!document.querySelector(".sr-app").classList.contains("sr-webgl-ready")'))
command(S,'click','button[aria-label="Open ABOUT ME"]');settle(200)
check('reduced motion has a poster with no video request',state('(()=>{const v=document.querySelector("video[data-section-video]");return !!v&&v.paused&&!v.getAttribute("src")&&v.poster.startsWith("data:image/png")})()'))
command(S,'press','Escape');settle(150)
command(S,'set','media','dark');command(S,'set','viewport','390','844');settle(400)
check('mobile preserves six cards with no overflow',state('document.documentElement.scrollWidth===390&&document.querySelectorAll("[data-resume-card]").length===6'))
command(S,'screenshot',str(ROOT/'outputs'/('premium-films-v7-mobile.png' if VERSION=='v7' else 'distinct-films-v6-mobile.png' if VERSION=='v6' else 'motion-studies-mobile.png')))
command(S,'scrollintoview','button[data-resume-card][aria-label="Open PROJECTS section"]')
command(S,'click','button[data-resume-card][aria-label="Open PROJECTS section"]');settle(1300)
check('mobile detail video plays',state('(()=>{const v=document.querySelector("video[data-section-video]");return !!v&&!v.paused&&v.readyState>=2})()'))
command(S,'press','Escape');settle(1100)
command(S,'set','viewport','1440','900');settle(3300)
check('desktop clears the mobile scroll offset',state('document.querySelector(".sr-app").scrollTop===0'))
command(S,'screenshot',str(ROOT/'outputs'/('premium-films-v7-desktop.png' if VERSION=='v7' else 'distinct-films-v6-desktop.png' if VERSION=='v6' else 'motion-studies-desktop.png')))
check('WebGL restores after media and viewport changes',state('document.querySelector(".sr-app").classList.contains("sr-webgl-ready")'))
check('no runtime errors',not command(S,'errors').strip())
metadata=[]
for key in ['about','experience','education','projects','skills','contact']:
    p=ROOT/('outputs/resume-films-'+VERSION)/key/'film.mp4' if VERSION!='v5' else ROOT/'outputs/resume-artifacts'/(key+'.mp4')
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)],capture_output=True,text=True,encoding='utf-8',check=True)
    data=json.loads(result.stdout);stream=data['streams'][0]
    seconds=8 if VERSION!='v5' else 6
    check(key+' export duration and 30 fps',float(data['format']['duration'])==seconds and stream['r_frame_rate']=='30/1' and stream['width']==1200 and stream['height']==704)
    metadata.append({'section':key,'bytes':p.stat().st_size,'duration':seconds,'fps':30,'size':[1200,704]})
(ROOT/'outputs'/('premium-films-v7-verification.json' if VERSION=='v7' else 'distinct-films-v6-verification.json' if VERSION=='v6' else 'section-motion-verification.json')).write_text(json.dumps({'checks':checks,'media':metadata},indent=2),encoding='utf-8')
