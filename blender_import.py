"""Animated marker/segment GLB export, Blender 4.5+ headless. JSON Y-up -> Blender Z-up."""
import json
import math
import sys
from fractions import Fraction
from pathlib import Path

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from export_motion import load_json, sha256_file, validate_motion


def basis_coordinates(v):
 return None if v is None else (v[0],-v[2],v[1])

def animation_timing(data):
 validate_motion(data)
 rate=Fraction(str(data["fps"])).limit_denominator(100000)
 if rate<=0:raise ValueError("MOTION_INVALID: Unrepresentable Blender frame rate")
 # Blender stores an integer FPS and a float FPS-base. Keep the rational pair
 # whenever its numerator fits Blender's range (e.g. 30000/1001, not 30/1).
 fps=rate.numerator if rate.numerator<=32767 else min(32767,max(1,round(float(rate))))
 base=rate.denominator if fps==rate.numerator else fps/float(rate)
 if not .1<=base<=1000000:raise ValueError("MOTION_INVALID: Unrepresentable Blender FPS-base")
 first=data["frames"][0]["t"]
 return fps,base,[(f["t"]-first)*(fps/base)+1 for f in data["frames"]]

def convert(v):
 from mathutils import Vector
 return None if v is None else Vector(basis_coordinates(v))
def make_mat(name,color):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1)
 m.use_nodes=True;n=m.node_tree.nodes.get("Principled BSDF")
 if n:
  n.inputs["Base Color"].default_value=(*color,1)
  n.inputs["Metallic"].default_value=.23
  n.inputs["Roughness"].default_value=.32
 return m
def main():
 global bpy
 import bpy
 args=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
 if len(args)!=3:raise ValueError("Usage: blender -b --python blender_import.py -- in.json out.blend out.glb")
 inp,blend,glb=(Path(x).resolve() for x in args)
 if blend==glb or inp in (blend,glb):raise ValueError("OUTPUT_EXISTS: Input/output paths must be distinct")
 if any(p.exists() or p.is_symlink() for p in (blend,glb)):raise ValueError("OUTPUT_EXISTS: Refusing overwrite")
 data=validate_motion(load_json(inp))
 frames=data["frames"];names=data["markers"]
 fps,base,keyframes=animation_timing(data)
 bpy.ops.object.select_all(action="SELECT");bpy.ops.object.delete(use_global=False)
 scene=bpy.context.scene;scene.render.fps=fps;scene.render.fps_base=base
 # Use Blender's actually stored FPS-base (float32) for timestamp/keyframe agreement.
 effective_fps=scene.render.fps/scene.render.fps_base
 keyframes=[(f["t"]-frames[0]["t"])*effective_fps+1 for f in frames]
 scene.frame_start=1;scene.frame_end=math.ceil(keyframes[-1])
 scene["kinelab_source_times_s"]=[f["t"] for f in frames]
 scene["kinelab_source_time_origin_s"]=frames[0]["t"]
 scene["kinelab_motion_schema"]=data["schema"]
 scene["kinelab_source_sha256"]=sha256_file(inp)
 scene["kinelab_basis"]="OpenSim (x,y,z) -> Blender (x,-z,y); GLB Y-up"
 if data.get("provenance"):scene["kinelab_provenance"]=json.dumps(data["provenance"],sort_keys=True)
 coll=bpy.data.collections.new("KineLab | 3D Motion Skeleton");scene.collection.children.link(coll)
 teal=make_mat("Surgical Teal | Joints",(0.018,.77,.67))
 copper=make_mat("Copper | Bones",(.8,.42,.20))
 joints={};bones={}
 for i,name in enumerate(names):
  if not any(f["xyz"][i] is not None for f in frames):continue
  bpy.ops.mesh.primitive_uv_sphere_add(segments=12,ring_count=8,radius=.022)
  ob=bpy.context.object;ob.name="Joint | "+name;ob.data.materials.append(teal)
  for c in list(ob.users_collection):c.objects.unlink(ob)
  coll.objects.link(ob);joints[i]=ob
 for ia,ib in data["bones"]:
  if ia not in joints or ib not in joints:continue
  bpy.ops.mesh.primitive_cylinder_add(vertices=10,radius=.009,depth=1)
  ob=bpy.context.object;ob.name=f"Bone | {names[ia]} - {names[ib]}"
  ob.rotation_mode="QUATERNION";ob.data.materials.append(copper)
  for c in list(ob.users_collection):c.objects.unlink(ob)
  coll.objects.link(ob);bones[(ia,ib)]=ob
 for fi,f in zip(keyframes,frames):
  coords=[convert(x) for x in f["xyz"]]
  for i,obj in joints.items():
   v=coords[i];obj.location=v if v is not None else (0,0,-999)
   obj.scale=(1,1,1) if v is not None else (0,0,0)
   obj.keyframe_insert(data_path="location",frame=fi)
   obj.keyframe_insert(data_path="scale",frame=fi)
  for (ia,ib),obj in bones.items():
   a,b=coords[ia],coords[ib]
   if a is None or b is None:obj.scale=(0,0,0)
   else:
    d=b-a;obj.location=(a+b)*.5
    if d.length>1e-8:obj.rotation_quaternion=d.to_track_quat("Z","Y")
    obj.scale=(1,1,d.length)
   for k in ["location","rotation_quaternion","scale"]:obj.keyframe_insert(data_path=k,frame=fi)
 for obj in coll.objects:
  if not obj.animation_data or not obj.animation_data.action:continue
  for curve in obj.animation_data.action.fcurves:
   for point in curve.keyframe_points:
    # Match the viewer's sample-and-hold. In particular, never interpolate a
    # visible marker toward the hidden sentinel before a missing sample.
    point.interpolation="CONSTANT"
 scene.frame_set(1)
 for p in (blend,glb):p.parent.mkdir(parents=True,exist_ok=True)
 if any(p.exists() for p in (blend,glb)):raise ValueError("OUTPUT_EXISTS: Destination appeared during import")
 bpy.ops.wm.save_as_mainfile(filepath=str(blend))
 bpy.ops.object.select_all(action="DESELECT")
 for obj in coll.objects:obj.select_set(True)
 # The installed glTF adapter multiplies FPS by FPS-base. Export a temporary
 # equivalent base-1 timeline so both adapter conventions yield real seconds.
 # The already saved BLEND retains its original rational rate and source keys.
 original_rate=(scene.render.fps,scene.render.fps_base,scene.frame_start,scene.frame_end)
 export_fps=min(32767,max(1,round(data["fps"])))
 factor=export_fps/effective_fps
 points=[]
 for obj in coll.objects:
  if not obj.animation_data or not obj.animation_data.action:continue
  for curve in obj.animation_data.action.fcurves:
   for point in curve.keyframe_points:
    points.append((point,point.co.x,point.handle_left.x,point.handle_right.x))
    point.co.x=(point.co.x-1)*factor
    point.handle_left.x=(point.handle_left.x-1)*factor
    point.handle_right.x=(point.handle_right.x-1)*factor
 scene.render.fps=export_fps;scene.render.fps_base=1
 scene.frame_start=0;scene.frame_end=math.ceil((frames[-1]["t"]-frames[0]["t"])*export_fps)
 try:
  bpy.ops.export_scene.gltf(filepath=str(glb),export_format="GLB",use_selection=True,
   export_animations=True,export_yup=True,export_force_sampling=False,export_extras=True,
   export_anim_slide_to_zero=True,export_optimize_animation_size=False)
 finally:
  scene.render.fps,scene.render.fps_base,scene.frame_start,scene.frame_end=original_rate
  for point,x,left,right in points:
   point.co.x=x;point.handle_left.x=left;point.handle_right.x=right
 print(f"BLENDER_EXPORT_OK frames={len(frames)} joints={len(joints)} bones={len(bones)} BLEND={blend} GLB={glb}")
if __name__=="__main__":main()
