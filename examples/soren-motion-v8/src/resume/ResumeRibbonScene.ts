import * as THREE from 'three';
import type { ResumeSection } from './resumeData';
import gsap from 'gsap';
import {ribbonVertex as vertex, reference} from './reference-motion.mjs';
import {SectionMedia} from './sectionMedia';
const RIBBON_FOV = reference.fov;
const ribbonCameraDistance = (height:number) => height / 2 / Math.tan(RIBBON_FOV * Math.PI / 360);
import { luxuryTokens, sectionAccents } from './luxuryTokens';

const W = 1200;
const H = 705;
const fragment = "precision highp float;\nuniform sampler2D uMap;\nuniform vec2 uSize;\nuniform float uOpacity;\nuniform float uRadius;\nuniform float uReflection;\nuniform float uHover;\nuniform float uSpeed;\nin vec2 vUv;\nout vec4 fragColor;\nfloat roundedDistance(vec2 p, vec2 size, float r){\n vec2 h=size*0.5;\n vec2 q=abs(p-h)-(h-r);\n return length(max(q,vec2(0.0)))+min(max(q.x,q.y),0.0)-r;\n}\nvoid main(){\n vec3 c=texture(uMap,vUv).rgb;\n float outer=pow(abs(vUv.x*2.0-1.0),1.6);\n float edge=0.034*exp(-pow((vUv.x-0.24)*7.0,2.0));\n c=c*(1.0-0.12*outer)+vec3(edge);\n c+=vec3(uHover*.06*exp(-pow((vUv.x-0.42)*6.0,2.0)));\n c+=vec3(.012,.009,.005)*uSpeed;\n float d=roundedDistance(vUv*uSize,uSize,uRadius);\n float aa=max(fwidth(d),0.65);\n float a=uOpacity*(1.0-smoothstep(-aa,aa,d));\n if(uReflection>0.5){\n   a*= (1.0-smoothstep(0.025,0.65,vUv.y));\n   c*=0.27;\n }\n fragColor=linearToOutputTexel(vec4(c,a));\n}";

interface Surface {
  id: string;
  logicalIndex: number;
  visualKey: string;
  texture: THREE.CanvasTexture;
  geometry: THREE.PlaneGeometry;
  material: THREE.ShaderMaterial;
  reflectionMaterial: THREE.ShaderMaterial;
  face: THREE.Mesh;
  reflection: THREE.Mesh;
}

function imageFor(url:string):Promise<HTMLImageElement|null> {
  return new Promise(resolve=>{const image=new Image();image.onload=()=>resolve(image);image.onerror=()=>resolve(null);image.src=url;});
}
function paintCard(section:ResumeSection, image:CanvasImageSource|null, target?:HTMLCanvasElement) {
  const canvas=target||document.createElement('canvas');
  if(canvas.width!==W||canvas.height!==H){canvas.width=W;canvas.height=H;}
  const ctx=canvas.getContext('2d');if(!ctx)throw new Error('2D canvas unavailable');
  ctx.fillStyle='#e9e5dc';ctx.fillRect(0,0,W,H);if(image)ctx.drawImage(image,0,0,W,H);
  const label=section.number+' / '+section.title;ctx.font='600 18px Arial';const width=ctx.measureText(label).width+28;
  ctx.fillStyle='rgba(241,238,232,.94)';ctx.beginPath();ctx.roundRect(24,14,width,29,14);ctx.fill();
  ctx.fillStyle='#242625';ctx.textBaseline='middle';ctx.fillText(label,38,29);return canvas;
}
export class ResumeRibbonScene {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly surfaces: Surface[] = [];
  private readonly canvas: HTMLCanvasElement;
  private readonly sections: ResumeSection[];

  private detailOpen = false;
  private targetSpeed = 0;
  private hoveredIndex: number | null = null;
  private activeUntil = 0;
  private raf: number | null = null;
  private disposed = false;
  private ready = false;
  private contextAvailable = true;
  private readonly onResize: () => void;
  private readonly onVisible: () => void;
  private readonly onContextLost: (event: Event) => void;
  private readonly onContextRestored: () => void;
  private selectedIndex = 0;
  private introStarted = 0;
  private sectionMedia: SectionMedia | null = null;
  private lastFrame = 0;

  constructor(canvas: HTMLCanvasElement, sections: ResumeSection[], onAvailability: (ready: boolean) => void = () => {}) {
    this.canvas = canvas;
    this.sections = sections;
    const context = canvas.getContext('webgl2', {alpha:true,antialias:true,powerPreference:'high-performance'});
    if (!context) throw new Error('WebGL2 unavailable; retain the HTML gallery.');
    this.renderer = new THREE.WebGLRenderer({
      canvas, context, alpha: true, antialias: true, powerPreference: 'high-performance'
    });
    this.contextAvailable = !context.isContextLost();
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
    this.renderer.setClearColor(0x000000, 0);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.camera = new THREE.PerspectiveCamera(RIBBON_FOV, 1, 1, 30000);
    this.resize();
    this.onResize = () => { this.resize(); this.wake(); };
    this.onVisible = () => { if (!document.hidden) this.wake(); };
    window.addEventListener('resize', this.onResize, { passive: true });
    document.addEventListener('visibilitychange', this.onVisible);
    this.onContextLost = event => {
      event.preventDefault();
      this.contextAvailable = false;
      this.ready = false;
      if (this.raf !== null) cancelAnimationFrame(this.raf);
      this.raf = null;
      onAvailability(false);
    };
    this.onContextRestored = () => {
      this.contextAvailable = true;
      if (this.disposed || !this.surfaces.length) return;
      this.ready = true;
      this.resize();
      this.wake();
      onAvailability(true);
    };
    canvas.addEventListener('webglcontextlost', this.onContextLost);
    canvas.addEventListener('webglcontextrestored', this.onContextRestored);
  }

  private resize() {
    if (this.disposed) return;
    const width = Math.max(1, window.innerWidth);
    const height = Math.max(1, window.innerHeight);
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.position.set(0, 0, ribbonCameraDistance(height));
    this.camera.lookAt(0, 0, 0);
    this.camera.updateProjectionMatrix();
  }

  async initialize(): Promise<boolean> {
    if (this.disposed) return false;
    const images = await Promise.all(this.sections.map(section => imageFor(section.image)));
    if (this.disposed) return false;

    this.sections.forEach((section, logicalIndex) => {
      const canvas = paintCard(section, images[logicalIndex]);
      const texture = new THREE.CanvasTexture(canvas);
      texture.colorSpace = THREE.SRGBColorSpace;
      texture.minFilter = THREE.LinearMipmapLinearFilter;
      texture.magFilter = THREE.LinearFilter;
      for (let cycle = 0; cycle < 3; cycle++) {
        const geometry = new THREE.PlaneGeometry(1, 1, 24, 24);
        const material = new THREE.ShaderMaterial({
          vertexShader: vertex,
          fragmentShader: fragment,
          glslVersion: THREE.GLSL3,
          depthTest: false,
          depthWrite: false,
          transparent: true,
          side: THREE.DoubleSide,
          uniforms: {
            uMap: { value: texture },
            uSize: { value: new THREE.Vector2(665,392) },
            uOpacity: { value: 1 },
            uRadius: { value: 8.5 },
            uReflection: { value: 0 },
            uHalfW: { value: window.innerWidth/2 },
            uSpeed: { value: 0 },
            uFocus: { value: 0 },
            uAccent: { value: new THREE.Color(luxuryTokens.palette.amber) },
            uAccentIntensity: { value: luxuryTokens.light.accentIntensity },
            uHover: { value: 0 }, uReveal: { value: 0 }
          }
        });
        const reflectionMaterial = material.clone();
        reflectionMaterial.uniforms.uReflection.value = 1;
        reflectionMaterial.uniforms.uOpacity.value = .30;
        const face = new THREE.Mesh(geometry, material);
        const reflection = new THREE.Mesh(geometry, reflectionMaterial);
        const id = cycle + '-' + section.id;
        const visualKey = cycle + '-' + logicalIndex;
        face.name = 'SOREN_' + id;
        reflection.name = 'SOREN_REFLECTION_' + id;
        this.scene.add(face,reflection);
        this.surfaces.push({
          id, logicalIndex, visualKey,
          texture, geometry, material, reflectionMaterial, face, reflection
        });
      }
    });
    this.sectionMedia = new SectionMedia(this, paintCard);
    this.canvas.dataset.cardCount = String(this.sections.length);
    this.canvas.dataset.meshCount = String(this.surfaces.length);
    this.ready = this.contextAvailable;
    if (this.ready) {this.introStarted=performance.now();this.wake();}
    return this.ready;
  }

  update(_index: number, open: boolean) {
    this.selectedIndex = _index;
    this.detailOpen = open;
    this.wake();
  }

  setMotionSpeed(speed: number) {
    if (this.disposed) return;
    this.targetSpeed = THREE.MathUtils.clamp(speed, 0, 1);
    this.wake();
  }

  setHovered(index: number, hovered: boolean) {
    this.hoveredIndex = hovered ? index : null;
    for(const surface of this.surfaces)gsap.to(surface.material.uniforms.uHover,{value:this.hoveredIndex===surface.logicalIndex?1:0,duration:.5,ease:'expo.out',overwrite:true});
    this.wake();
  }

  wake() {
    if (this.disposed || !this.ready || document.hidden) return;
    this.activeUntil = Math.max(this.activeUntil, performance.now() + 1800);
    if (this.raf == null) this.raf = requestAnimationFrame(this.draw);
  }

  private readonly draw = (time: number) => {
    this.raf = null;
    if (this.disposed || !this.ready || document.hidden) return;
    const midX = window.innerWidth / 2;
    const midY = window.innerHeight / 2;
    const alpha = 1-Math.pow(.9,Math.min(64,this.lastFrame ? time-this.lastFrame : 16.667)/16.667);
    this.lastFrame = time;
    const accent = new THREE.Color(luxuryTokens.palette[sectionAccents[this.selectedIndex]]);
    const track = document.querySelector<HTMLElement>('.sr-ribbon-track');
    if (!track) return;
    const trackRect = track.getBoundingClientRect();
    const focus = Number(track.dataset.focus || 0);
    for (let index = 0; index < this.surfaces.length; index++) {
      const surface = this.surfaces[index];
      const node = document.querySelector<HTMLButtonElement>('[data-resume-visual="' + surface.visualKey + '"]');
      if (!node) {
        surface.face.visible = false;
        surface.reflection.visible = false;
        continue;
      }
      // Layout offsets stay unprojected; the shared curve maps both faces and DOM hit regions.
      const rect = { left: trackRect.left + node.offsetLeft, top: trackRect.top + node.offsetTop,
        width: node.offsetWidth, height: node.offsetHeight,
        right: trackRect.left + node.offsetLeft + node.offsetWidth,
        bottom: trackRect.top + node.offsetTop + node.offsetHeight };
      if (rect.width < 1 || rect.height < 1 ||
          rect.right < -window.innerWidth * .5 || rect.left > window.innerWidth * 1.5) {
        surface.face.visible = false;
        surface.reflection.visible = false;
        continue;
      }
      const relative = (rect.left + rect.width/2 - midX)/Math.max(midX,1);
      const distance = Math.abs(relative);
      const width = rect.width;
      surface.face.userData.mediaVisible = rect.right>0 && rect.left<window.innerWidth;
      surface.face.visible = true;

      const hoverVal = surface.material.uniforms.uHover.value;
      const zOffset = 0;
      surface.face.position.set(rect.left + rect.width / 2 - midX, midY - (rect.top + rect.height / 2), zOffset);
      surface.face.scale.set(width, rect.height, 1);
      surface.face.renderOrder = (30 - distance) + hoverVal * 12;
      surface.material.uniforms.uSize.value.set(rect.width, rect.height);
      surface.material.uniforms.uHalfW.value = midX;
      surface.material.uniforms.uSpeed.value = this.targetSpeed;
      surface.material.uniforms.uFocus.value = focus;
      surface.material.uniforms.uAccent.value.lerp(accent,alpha);
      const reveal=gsap.parseEase('expo.out')(Math.max(0,Math.min(1,(time-this.introStarted-1150-Math.min(surface.logicalIndex,3)*50)/1250)));
      surface.material.uniforms.uReveal.value=reveal;
      surface.reflectionMaterial.uniforms.uReveal.value=reveal;
      surface.material.uniforms.uOpacity.value=(this.detailOpen ? .72 : 1)*Math.min(1,reveal*2);

      const reflectTop = rect.bottom + 20;
      const reflectHeight = rect.height * .63;
      surface.reflection.visible = window.innerWidth >= 900 && reflectTop < window.innerHeight;
      surface.reflection.position.set(rect.left + rect.width / 2 - midX, midY - (reflectTop + reflectHeight / 2), -3);
      surface.reflection.scale.set(width, -reflectHeight, 1);
      surface.reflection.renderOrder = 5 - distance;
      surface.reflectionMaterial.uniforms.uSize.value.set(rect.width, reflectHeight);
      surface.reflectionMaterial.uniforms.uHalfW.value = midX;
      surface.reflectionMaterial.uniforms.uSpeed.value = this.targetSpeed;
      surface.reflectionMaterial.uniforms.uFocus.value = focus;
      surface.reflectionMaterial.uniforms.uAccent.value.copy(surface.material.uniforms.uAccent.value);
      surface.reflectionMaterial.uniforms.uHover.value = 0;
    }
    this.sectionMedia?.update();
    this.renderer.render(this.scene, this.camera);
    if (this.sectionMedia?.playing || time < Math.max(this.activeUntil,this.introStarted+2800)) this.raf = requestAnimationFrame(this.draw);
  };

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.sectionMedia?.dispose();
    window.removeEventListener('resize', this.onResize);
    document.removeEventListener('visibilitychange', this.onVisible);
    this.canvas.removeEventListener('webglcontextlost', this.onContextLost);
    this.canvas.removeEventListener('webglcontextrestored', this.onContextRestored);
    if (this.raf !== null) cancelAnimationFrame(this.raf);
    const textures = new Set<THREE.Texture>();
    this.surfaces.forEach(s => {
      gsap.killTweensOf(s.material.uniforms.uHover);
      this.scene.remove(s.face, s.reflection);
      s.material.dispose();
      s.reflectionMaterial.dispose();
      s.geometry.dispose();
      textures.add(s.texture);
    });
    textures.forEach(t => t.dispose());
    this.surfaces.length = 0;
    this.renderer.dispose();
    // The mounted canvas is reused after responsive/reduced-motion changes.
    delete this.canvas.dataset.cardCount;
    delete this.canvas.dataset.meshCount;
  }
}
