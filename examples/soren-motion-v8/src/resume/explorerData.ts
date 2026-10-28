import {resumeSections} from './resumeData';

export const projectIds = ['kinelab','soren-mcp','steppr','living-resume','biomech-lab'] as const;
export type ProjectId = typeof projectIds[number];
const blocks = resumeSections.find(s=>s.id==='projects')!.blocks;
export const projects = [
  {id:'kinelab', title:'KineLab PT', short:'Movement', status:'Prototype', overview:blocks[0].value,
    problem:'Explore how ordinary cameras can support movement-analysis workflows.',
    build:'Dual-camera capture, pose estimation, and a 3D review interface.',
    evidence:'Explore the existing demo motion export in the viewer. This is a software demonstration.',
    limits:'Calibration, synchronization, and physical accuracy require separate validation.', stack:['Python','Pose analysis','Three.js']},
  {id:'soren-mcp', title:'SOREN MCP V3', short:'Systems', status:'Study', overview:blocks[1].value,
    problem:'Keep coding work connected to source material and clear plans.',
    build:'An exploration of coding agents, MCP tools, and orchestration workflows.',
    evidence:'The workflow below illustrates the idea. It is not a live service or execution trace.',
    limits:'A public case study and production outcomes have not been supplied.', stack:['MCP','Planning','Coding agents']},
  {id:'steppr', title:'Steppr / Spline', short:'Environment', status:'Study', overview:blocks[2].value,
    problem:'Explore how lighting and navigation change the experience of a 3D room.',
    build:'A Spline room study with configured Day/Night lighting and first-person navigation.',
    evidence:'Open the linked Spline project to inspect the actual environment.',
    limits:'The lighting control here is an interface study; it does not control the external Spline scene.', stack:['Spline','Lighting','Interaction']},
  {id:'living-resume', title:'Living Résumé', short:'Interface', status:'Prototype', overview:blocks[3].value,
    problem:'Make a multidisciplinary résumé engaging while keeping its content readable.',
    build:'Six films, a curved Three.js ribbon, GSAP transitions, and React section explorers.',
    evidence:'The interface you are using is the working prototype. All six sections remain HTML.',
    limits:'Visual motion is a design study. Device performance varies.', stack:['React','TypeScript','Three.js','GSAP']},
  {id:'biomech-lab', title:'Biomechanical Lab', short:'Cybernetics', status:'Study', overview:blocks[4]?.value || 'Interactive kinematic cybernetics study linking NVIDIA SimReady robotics with human biomechanics.',
    problem:'Connect industrial articulated robotics with human movement kinematics in a real-time web shader and 1440p60 film.',
    build:'NVIDIA SimReady Franka arm, CC BY 4.0 BodyParts3D musculoskeletal joints, interactive GLSL kinematic shaders, and Remotion/Hyperframes hero film.',
    evidence:'Interact with the 3D kinematic canvas and joint telemetry below. Real-time WebGL rendering with GPU instancing and zero runtime bloat.',
    limits:'Kinematic telemetry illustrates motion trajectories and joint velocities; clinical torque validation requires lab instrumentation.', stack:['Three.js','SimReady','GLSL','Remotion','Hyperframes']},
] as const;

export const skillLinks = [
  {name:'React', category:'Interface', projects:['living-resume'], note:'Section interfaces, state, and semantic navigation.'},
  {name:'Three.js', category:'3D', projects:['living-resume','kinelab','biomech-lab'], note:'The curved ribbon, movement visualization, and real-time kinematic cybernetics canvas.'},
  {name:'GSAP', category:'Motion', projects:['living-resume'], note:'The measured ribbon hover and section flight.'},
  {name:'Spline', category:'3D', projects:['steppr'], note:'The Steppr room, lighting, and navigation study.'},
  {name:'Python', category:'Movement', projects:['kinelab'], note:'Movement-analysis and data-processing experiments.'},
  {name:'MCP', category:'Systems', projects:['soren-mcp'], note:'Tool orchestration and source-grounded coding workflows.'},
] as const;

export const githubUrl = resumeSections.find(s=>s.id==='contact')!.blocks.find(b=>b.label==='GITHUB')!.href!;
export const splineUrl = blocks[2].href!;
export function projectTitle(id:string) {return projects.find(p=>p.id===id)?.title || id;}
export function frameFromTime(time:number, fps:number, count:number) {
  return count>0 ? Math.min(count-1,Math.max(0,Math.floor(time*fps))) : 0;
}
