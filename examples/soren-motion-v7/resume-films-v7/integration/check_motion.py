import json
import pathlib
import subprocess
from probe_reference import evaluate, BIN

OUT=pathlib.Path(__file__).parent/'motion-evidence'
OUT.mkdir(exist_ok=True)
REFERENCE='jesper-motion-01a18094'
CANDIDATE='jesper-candidate-01a18094'

def command(session,*args):
    result=subprocess.run([BIN,'--session',session,*args],capture_output=True,text=True,encoding='utf-8')
    if result.returncode:raise RuntimeError(result.stdout+result.stderr)
    return result.stdout

def trace(session,reference):
    selector='article' if reference else '.sr-card'
    position='parseFloat(card.style.transform.match(/translate3d\\(([-.0-9]+)/)?.[1]||0)' if reference else 'Number(track.dataset.position)'
    code='''(async()=>{
      const track=document.querySelector(SELECTOR).parentElement;
      await new Promise(done=>setTimeout(done,3200));
      const card=track.querySelectorAll(SELECTOR)[2];
      const initial=POSITION,start=performance.now(),samples=[];
      card.dispatchEvent(new WheelEvent('wheel',{deltaY:550,deltaX:0,bubbles:true,cancelable:true}));
      await new Promise(done=>{function frame(now){samples.push([now-start,POSITION-initial]);if(now-start<1400)requestAnimationFrame(frame);else done();}requestAnimationFrame(frame);});
      return JSON.stringify({viewport:[innerWidth,innerHeight],samples});
    })()'''.replace('SELECTOR',json.dumps(selector)).replace('POSITION',position)
    return evaluate(code,session)

if __name__=='__main__':
    results={}
    for session,is_reference in [(REFERENCE,True),(CANDIDATE,False)]:
        command(session,'reload')
        data=trace(session,is_reference)
        name='reference' if is_reference else 'candidate'
        (OUT/(name+'-wheel.json')).write_text(json.dumps(data),encoding='utf-8')
        results[name]={'frames':len(data['samples']),'travel':data['samples'][-1][1],'viewport':data['viewport']}
    reference=json.loads((OUT/'reference-wheel.json').read_text())['samples']
    candidate=json.loads((OUT/'candidate-wheel.json').read_text())['samples']
    def sample(rows,time):
        for i in range(1,len(rows)):
            if rows[i][0]>=time:
                a,b=rows[i-1],rows[i]
                return a[1]+(b[1]-a[1])*(time-a[0])/(b[0]-a[0])
        return rows[-1][1]
    pairs=[{'ms':time,'referencePx':sample(reference,time),'candidatePx':sample(candidate,time)} for time in [50,100,200,400,800,1200]]
    results['trajectory']=pairs
    results['maxErrorPx']=max(abs(p['referencePx']-p['candidatePx']) for p in pairs)
    offsets=[n/10 for n in range(-100,101)]
    phase=min(offsets,key=lambda offset:max(abs(sample(reference,t)-sample(candidate,t+offset)) for t in [50,100,200,400,800,1200]))
    results['samplingPhaseOffsetMs']=phase
    results['phaseAlignedMaxErrorPx']=max(abs(sample(reference,t)-sample(candidate,t+phase)) for t in [50,100,200,400,800,1200])
    results['settledTravelDifferencePx']=abs(results['reference']['travel']-results['candidate']['travel'])
    assert results['settledTravelDifferencePx']<4,'wheel endpoint drift'
    assert results['phaseAlignedMaxErrorPx']<8,'wheel trajectory drift beyond one sampling frame'
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps(results))
