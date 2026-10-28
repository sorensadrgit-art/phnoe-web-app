"""Initialize a clean Windows Pose2Sim phone + webcam project, preserving packaged demos."""
from pathlib import Path
from datetime import datetime, timezone
import argparse, json
import Pose2Sim
import rtoml
from session_contract import ROLES, sha256_file, validate_session

ROOT=Path(__file__).resolve().parent
SAMPLE=Path(Pose2Sim.__file__).parent/"Demo_SinglePerson"/"Config.toml"
PROJ=ROOT/"projects"/"kinelab-dualcam"
DIRS=["raw","videos","exports","calibration/intrinsics/cam01","calibration/intrinsics/cam02","calibration/extrinsics"]
def register_captures(project, session_id, kind="real"):
    captures={}
    for role in ROLES:
        path=project/"raw"/(role+".mp4")
        if not path.is_file():raise ValueError("INPUT_MISSING: "+str(path))
        captures[role]={"path":path.relative_to(project).as_posix(),"sha256":sha256_file(path)}
    data={"schema":"kinelab.session.v1","session_id":session_id,"kind":kind,"subject_count":1,
          "camera_ids":["cam01","cam02"],"created_at":datetime.now(timezone.utc).isoformat(),"captures":captures}
    validate_session(data,project)
    out=project/"session.json"
    if out.exists():raise ValueError("OUTPUT_EXISTS: "+str(out))
    with out.open("x",encoding="utf-8") as stream:json.dump(data,stream,indent=2)
    return data

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--project",type=Path,default=PROJ)
    p.add_argument("--session-id")
    p.add_argument("--kind",choices=("real","demo"),default="real")
    p.add_argument("--register-captures",action="store_true",help="Register the six raw/<role>.mp4 files in an existing project")
    a=p.parse_args()
    project=a.project.resolve()
    if a.register_captures:
        if not (project/"Config.toml").is_file():p.error("Missing Config.toml")
        try:register_captures(project,a.session_id or project.name,a.kind)
        except ValueError as error:p.error(str(error))
        print("CAPTURES_REGISTERED="+str(project/"session.json"));return
    if project.exists():
        raise SystemExit(f"Refusing to overwrite {project}")
    data=rtoml.load(SAMPLE)
    data["project"].update(frame_rate=30,frame_range="auto",multi_person=False)
    data["pose"].update(pose_model="Body_with_feet",device="CPU",backend="onnxruntime",parallel_workers_pose=2,display_detection=False)
    data["synchronization"].update(synchronization_gui=False,display_sync_plots=False,save_sync_plots=True,time_range_around_maxspeed=4.0)
    data["calibration"]["calibration_type"]="calculate"
    calc=data["calibration"]["calculate"]
    calc["save_debug_images"]=True
    calc["intrinsics"].update(overwrite_intrinsics=True,intrinsics_extension="mp4",extract_every_N_sec=0.5,intrinsics_corners_nb=[7,9],intrinsics_square_size=20,show_detection_intrinsics=False)
    ext=calc["extrinsics"]
    ext.update(calculate_extrinsics=True,extrinsics_method="board",extrinsics_extension="mp4",show_reprojection_error=False,moving_cameras=False)
    ext["board"].update(board_position="horizontal",extrinsics_corners_nb=[7,9],extrinsics_square_size=20,show_reprojection_error=False)
    data["triangulation"]["min_cameras_for_triangulation"]=2
    data["triangulation"]["reproj_error_threshold_triangulation"]=15
    for name in DIRS: (project/name).mkdir(parents=True,exist_ok=True)
    (project/"Config.toml").write_text(rtoml.dumps(data),encoding="utf-8")
    template={"schema":"kinelab.session.v1","session_id":a.session_id or project.name,"kind":a.kind,"subject_count":1,
              "camera_ids":["cam01","cam02"],"created_at":None,
              "captures":{role:{"path":"raw/"+role+".mp4","sha256":None} for role in ROLES},
              "status":"not configured; place all six originals in raw and run --register-captures"}
    (project/"session-template.json").write_text(json.dumps(template,indent=2),encoding="utf-8")
    (project/"raw"/"README.txt").write_text(
      "Provide: cam01_intrinsics (phone), cam02_intrinsics (webcam), cam01_board, cam02_board, cam01_trial, cam02_trial. "
      "Keep original footage private; use normalize_capture.py after recording. Board: 8x10 squares with 20mm sides. "
      "Camera placements and lens settings must not change between board calibration and trial.\n",encoding="utf-8")
    print(f"PROJECT_CREATED={project}")
    print(f"TEMPLATE={SAMPLE}; TWO_CAMERAS; CFR_30FPS; 1280x720")
if __name__=="__main__":main()
