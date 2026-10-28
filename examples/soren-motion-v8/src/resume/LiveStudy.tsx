import {useEffect,useRef} from 'react';
import * as THREE from 'three';
import {GLTFLoader} from 'three/examples/jsm/loaders/GLTFLoader.js';
import {MeshoptDecoder} from 'three/examples/jsm/libs/meshopt_decoder.module.js';
import {OrbitControls} from 'three/examples/jsm/controls/OrbitControls.js';
import {RoomEnvironment} from 'three/examples/jsm/environments/RoomEnvironment.js';

type Props={kind:'anatomy'|'motion';layer?:string;separation?:number;frame?:number;view?:string;rotation?:number;zoom?:number;reset?:number;onReady?:(frames:number,fps:number)=>void;onFailure:()=>void};
type Demo={fps:number;bones:number[][];frames:{t:number;xyz:number[][]}[]};
export default function LiveStudy(props:Props) {
  const canvas=useRef<HTMLCanvasElement>(null);
  const current=useRef(props);current.current=props;
  const control=useRef<(()=>void)|null>(null);
  useEffect(()=>{
    const element=canvas.current;if(!element)return;
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({canvas:element,antialias:true,alpha:true});}catch{current.current.onFailure();return;}
    let disposed=false;
    const scene=new THREE.Scene(),root=new THREE.Group();scene.add(root);
    const camera=new THREE.PerspectiveCamera(34,1,.01,100);
    const controls=new OrbitControls(camera,element);
    controls.enablePan=false;controls.minDistance=2.7;controls.maxDistance=9;controls.enableDamping=false;
    renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));renderer.outputColorSpace=THREE.SRGBColorSpace;
    renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.2;
    const generator=new THREE.PMREMGenerator(renderer),room=new RoomEnvironment(),environment=generator.fromScene(room,.04);
    scene.environment=environment.texture;generator.dispose();room.dispose();
    scene.add(new THREE.HemisphereLight(0xfff6e5,0x224139,2.4));
    const key=new THREE.DirectionalLight(0xfff2d5,3.5);key.position.set(2,4,3);scene.add(key);
    const rim=new THREE.DirectionalLight(0x9edcc9,2);rim.position.set(-3,2,-3);scene.add(rim);
    const render=()=>{if(!disposed&&!document.hidden)renderer.render(scene,camera);};
    controls.addEventListener('change',render);
    let demo:Demo|null=null,parts:THREE.Mesh[]=[],markers:THREE.Mesh[]=[],bones:THREE.Mesh[]=[];
    let priorReset:number|undefined=-1,priorView='',priorRotation=-1;
    const release=(object:THREE.Object3D)=>object.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();const materials=Array.isArray(o.material)?o.material:[o.material];materials.forEach(m=>{for(const value of Object.values(m))if(value instanceof THREE.Texture)value.dispose();m.dispose();});}});
    const apply=()=>{
      if(disposed)return;
      const p=current.current;
      if(priorReset!==p.reset||priorView!==p.view){
        camera.position.set(p.view==='side'?5.6:0,1.3,p.view==='side'?0:5.6);controls.target.set(0,.1,0);controls.update();
        priorReset=p.reset;priorView=p.view||'';
      }
      if(priorRotation!==p.rotation){root.rotation.y=(p.rotation||0)*Math.PI/180;priorRotation=p.rotation||0;}
      camera.zoom=p.zoom||1;camera.updateProjectionMatrix();
      if(p.kind==='anatomy')for(const mesh of parts){
        const layer=mesh.name.split('-')[0];mesh.visible=p.layer==='all'||!p.layer||p.layer===layer;
        mesh.position.x=mesh.userData.baseX+(layer==='muscle'?1:layer==='tendon'?2:0)*(p.separation||0)*.42/mesh.userData.scale;
      }
      if(demo){
        const positions=demo.frames[Math.min(demo.frames.length-1,Math.max(0,p.frame||0))].xyz;
        const center=demo.frames[0].xyz[0];
        const points=positions.map(x=>new THREE.Vector3(x[0]-center[0],x[1]-.9,x[2]-center[2]));
        markers.forEach((m,i)=>m.position.copy(points[i]));
        demo.bones.forEach(([a,b],i)=>{const delta=points[b].clone().sub(points[a]);bones[i].position.copy(points[a]).add(points[b]).multiplyScalar(.5);bones[i].scale.set(1,delta.length(),1);bones[i].quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),delta.normalize());});
        element.dataset.frame=String(p.frame||0);
      }
      render();
    };
    control.current=apply;
    const resize=()=>{const bounds=element.getBoundingClientRect();renderer.setSize(Math.max(1,bounds.width),Math.max(1,bounds.height),false);camera.aspect=Math.max(1,bounds.width)/Math.max(1,bounds.height);camera.updateProjectionMatrix();render();};
    const observer=new ResizeObserver(resize);observer.observe(element);
    const visible=()=>render();document.addEventListener('visibilitychange',visible);
    const lost=(event:Event)=>{event.preventDefault();if(!disposed)current.current.onFailure();};element.addEventListener('webglcontextlost',lost);
    const abort=new AbortController();
    if(props.kind==='anatomy')new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).load(import.meta.env.BASE_URL+'models/anatomy-low.glb',g=>{
      if(disposed){release(g.scene);return;}
      const discarded:THREE.Object3D[]=[];
      g.scene.traverse(o=>{if(o instanceof THREE.Mesh){
        if(o.name.includes('skin')){discarded.push(o);return;}
        const previous=Array.isArray(o.material)?o.material:[o.material];previous.forEach(m=>m.dispose());
        o.material=new THREE.MeshPhysicalMaterial({color:o.name.startsWith('bone')?'#ddcda7':o.name.startsWith('tendon')?'#b5783b':'#763a45',roughness:.45,metalness:.08,clearcoat:.2});
        o.userData.baseX=o.position.x;parts.push(o);
      }});
      discarded.forEach(o=>{o.removeFromParent();release(o);});
      const box=new THREE.Box3().setFromObject(g.scene),size=box.getSize(new THREE.Vector3()),center=box.getCenter(new THREE.Vector3()),scale=3.1/size.y;
      g.scene.position.copy(center).multiplyScalar(-scale);g.scene.scale.setScalar(scale);
      parts.forEach(m=>m.userData.scale=scale);root.add(g.scene);
      element.dataset.loaded='true';current.current.onReady?.(0,0);apply();
    },undefined,()=>{if(!disposed)current.current.onFailure();});
    else fetch(import.meta.env.BASE_URL+'models/demo.motion.json',{signal:abort.signal}).then(r=>{if(!r.ok)throw Error('Demo unavailable');return r.json() as Promise<Demo>;}).then(data=>{
      if(disposed)return;
      if(!data.frames?.length||!data.bones?.length||!data.frames.every(f=>f.xyz?.length===data.frames[0].xyz.length&&f.xyz.every(v=>v.length===3&&v.every(Number.isFinite))))throw Error('Invalid demo');
      demo=data;
      const geometry=new THREE.SphereGeometry(.025,12,8),material=new THREE.MeshStandardMaterial({color:'#e8bd88',metalness:.35,roughness:.35});
      markers=data.frames[0].xyz.map(()=>{const m=new THREE.Mesh(geometry,material);root.add(m);return m;});
      const boneGeometry=new THREE.CylinderGeometry(.013,.013,1,10);
      bones=data.bones.map(()=>{const m=new THREE.Mesh(boneGeometry,material);root.add(m);return m;});
      const floor=new THREE.GridHelper(3.2,8,0x517575,0x294449);floor.position.y=-.91;root.add(floor);
      element.dataset.loaded='true';current.current.onReady?.(data.frames.length,data.fps);apply();
    }).catch(error=>{if(!disposed&&error.name!=='AbortError')current.current.onFailure();});
    resize();apply();
    return()=>{disposed=true;abort.abort();control.current=null;observer.disconnect();controls.removeEventListener('change',render);controls.dispose();document.removeEventListener('visibilitychange',visible);element.removeEventListener('webglcontextlost',lost);release(scene);scene.traverse(o=>{if(o instanceof THREE.LineSegments){o.geometry.dispose();(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});environment.dispose();renderer.dispose();};
  },[props.kind]);
  useEffect(()=>{control.current?.();},[props.layer,props.separation,props.frame,props.view,props.rotation,props.zoom,props.reset]);
  return <canvas ref={canvas} className="ex-live-canvas" aria-hidden="true" data-study={props.kind}/>;
}
