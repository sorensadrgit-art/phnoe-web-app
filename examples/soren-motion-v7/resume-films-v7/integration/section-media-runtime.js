// Share one decoder and texture per section across the three ribbon cycles.
class SectionMedia {
  constructor(scene,paint){
    this.scene=scene;this.paint=paint;this.playing=false;
    this.entries=scene.sections.map((section,index)=>({section,index,video:null,last:-1,blocked:false}));
    this.motion=matchMedia('(prefers-reduced-motion: reduce)');
    this.visibility=()=>{if(document.hidden||this.motion.matches)this.pause();else scene.wake()};
    document.addEventListener('visibilitychange',this.visibility);
    this.motion.addEventListener('change',this.visibility);
    scene.canvas.dataset.motionStudies=String(this.entries.length);
  }
  pause(){this.playing=false;for(const e of this.entries)e.video?.pause()}
  update(){
    this.playing=false;
    if(document.hidden||this.motion.matches||this.scene.detailOpen){this.pause();return}
    for(const entry of this.entries){
      const surfaces=this.scene.surfaces.filter(s=>s.logicalIndex===entry.index);
      const visible=surfaces.some(s=>s.face.visible&&s.face.userData.mediaVisible);
      if(!visible){entry.video?.pause();continue}
      if(!entry.video){
        const video=document.createElement('video');
        video.muted=true;video.loop=true;video.playsInline=true;video.preload='metadata';
        video.src=SECTION_VIDEOS[entry.section.id];
        video.addEventListener('loadeddata',()=>this.scene.wake(),{once:true});
        entry.video=video;
      }
      const video=entry.video;
      if(video.paused&&!entry.blocked)video.play().then(()=>this.scene.wake()).catch(()=>{entry.blocked=true});
      if(!video.paused)this.playing=true;
      if(video.readyState>=2&&Math.abs(video.currentTime-entry.last)>1/40){
        const texture=surfaces[0].texture;
        this.paint(entry.section,video,texture.image);
        texture.needsUpdate=true;entry.last=video.currentTime;
        this.scene.canvas.dataset.mediaFrames=String((Number(this.scene.canvas.dataset.mediaFrames)||0)+1);
      }
    }
    this.scene.canvas.dataset.playingStudies=String(this.entries.filter(e=>e.video&&!e.video.paused).length);
  }
  dispose(){
    this.pause();document.removeEventListener('visibilitychange',this.visibility);
    this.motion.removeEventListener('change',this.visibility);
    for(const e of this.entries)if(e.video){e.video.removeAttribute('src');e.video.load()}
  }
}

function bindSectionVideo(video,id){
  const motion=matchMedia('(prefers-reduced-motion: reduce)');
  const sync=()=>{
    if(document.hidden||motion.matches){video.pause();if(motion.matches){video.removeAttribute('src');video.load()}return}
    if(!video.getAttribute('src'))video.src=SECTION_VIDEOS[id];
    video.play().catch(()=>{});
  };
  motion.addEventListener('change',sync);document.addEventListener('visibilitychange',sync);sync();
  return ()=>{motion.removeEventListener('change',sync);document.removeEventListener('visibilitychange',sync);video.pause();video.removeAttribute('src');video.load()};
}
