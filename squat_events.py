"""Conservative 2D squat-repetition *candidates* from HALPE26 source landmarks.

This is a pure, bounded analysis component. It never opens video, guesses the
exercise being performed, modifies recordings, or reports clinical ROM/accuracy.
It requires explicit operator confirmation of a side view and a squat task,
stable initial standing frames, usable bilateral hip/knee/ankle/shoulder landmarks,
and a completed descent -> deep-position -> ascent -> stand state sequence.

Camera/image-plane knee angles and hip image displacement are heuristic only.
"""
from __future__ import annotations

from datetime import datetime, timezone
import math
from statistics import median

from gait_events import validate_2d_trajectories, GaitEvidenceError

SQUAT_ALGORITHM_VERSION = "kinelab-t5-squat-2d-phase-v1"
FPS = 30
CONFIDENCE_SCORE_THRESHOLD = .43
SMOOTH_HALF_WINDOW = 2
BASELINE_FRAMES = 20
REQUIRED_INDICES = (5,6,11,12,13,14,15,16)
BEGIN_FLEX_DEGREES = 16.
BEGIN_HIP_DROP = .10
BOTTOM_FLEX_DEGREES = 45.
BOTTOM_HIP_DROP = .33
END_FLEX_DEGREES = 18.
END_HIP_DROP = .14
MIN_REP_DURATION = 20
MAX_REP_DURATION = 240


class SquatEvidenceError(ValueError):
    """Refuse unsupported squat classification rather than inventing motions."""


def require(predicate, reason):
    if not predicate:
        raise SquatEvidenceError(reason)


def _angle(hip, knee, ankle):
    ax,ay=float(hip[0]-knee[0]),float(hip[1]-knee[1])
    bx,by=float(ankle[0]-knee[0]),float(ankle[1]-knee[1])
    norm=math.hypot(ax,ay)*math.hypot(bx,by)
    if not math.isfinite(norm) or norm<16:
        return None
    value=(ax*bx+ay*by)/norm
    return math.degrees(math.acos(max(-1.,min(1.,value))))


def _feature(record,image_width,image_height):
    index=record["frame_index"]
    scores=record["confidence"]
    xy=record["xy_pixels"]
    result={"frame_index":index,"time_seconds":round(index/FPS,6),
            "knee_angle_image_degrees":None,
            "left_knee_image_degrees":None,"right_knee_image_degrees":None,
            "hip_y_pixels":None,"torso_length_pixels":None,
            "flexion_image_degrees":None,"hip_descent_torso_units":None,
            "phase":"unavailable","measured":False}
    if record["people_detected"]!=1 or scores is None or xy is None:
        return result
    for idx in REQUIRED_INDICES:
        point=xy[idx]
        if (scores[idx]<CONFIDENCE_SCORE_THRESHOLD or point is None or
                not (0 <= point[0] <= image_width and 0 <= point[1] <= image_height)):
            return result
    left=_angle(xy[11],xy[13],xy[15])
    right=_angle(xy[12],xy[14],xy[16])
    if left is None or right is None:
        return result
    hips_y=(xy[11][1]+xy[12][1])/2
    shoulder_y=(xy[5][1]+xy[6][1])/2
    torso_len=math.hypot(
        (xy[5][0]+xy[6][0]-xy[11][0]-xy[12][0])/2,
        shoulder_y-hips_y,
    )
    if not 12 <= torso_len <= max(image_width,image_height):
        return result
    result.update(
        knee_angle_image_degrees=round((left+right)/2,5),
        left_knee_image_degrees=round(left,5),
        right_knee_image_degrees=round(right,5),
        hip_y_pixels=float(hips_y),torso_length_pixels=float(torso_len),
        measured=True,
    )
    return result


def _baseline(features):
    early=[f for f in features[:BASELINE_FRAMES] if f["measured"]]
    require(len(early)>=BASELINE_FRAMES-2,
            "Stable standing baseline missing: >=18 usable frames needed at start")
    angles=[f["knee_angle_image_degrees"] for f in early]
    hips=[f["hip_y_pixels"] for f in early]
    torso=[f["torso_length_pixels"] for f in early]
    baseline_angle=median(angles)
    torso_scale=median(torso)
    require(145 <= baseline_angle <= 185,
            "Standing baseline knee angle not extended enough for squat image analysis")
    require(max(angles)-min(angles)<=10,
            "Standing baseline unstable: initial pose varies excessively")
    require((max(hips)-min(hips))/torso_scale<=.15,
            "Standing baseline unstable: pelvis moved during baseline")
    return baseline_angle,median(hips),torso_scale


def _median_without_interpolation(values):
    """Median 5 *consecutive* complete observations; do not fill any absent index."""
    smooth=[None]*len(values)
    for i in range(SMOOTH_HALF_WINDOW,len(values)-SMOOTH_HALF_WINDOW):
        neighborhood=values[i-SMOOTH_HALF_WINDOW:i+SMOOTH_HALF_WINDOW+1]
        if all(v is not None and math.isfinite(v) for v in neighborhood):
            smooth[i]=float(median(neighborhood))
    return smooth


def analyze_squats(
    evidence, role, source_sha256, *,
    camera_view, activity_confirmed, image_width, image_height
):
    """Return explicit, unvalidated 2D squat-repetition candidate phases."""
    require(activity_confirmed is True,"Squat activity must be explicitly confirmed by operator")
    require(camera_view=="side",
            "Conservative 2D squat phase counting requires an operator-identified side view")
    require(type(image_width) is int and 320<=image_width<=8192 and
            type(image_height) is int and 240<=image_height<=8192,
            "Invalid source video geometry")
    try:
        frames=validate_2d_trajectories(evidence,role,source_sha256)
    except GaitEvidenceError as exc:
        raise SquatEvidenceError("Invalid source-bound 2D observation: "+str(exc)) from exc
    require(len(frames)>=60,"At least two seconds of full source observations required")
    features=[_feature(row,image_width,image_height) for row in frames]
    baseline_knee,baseline_hip,torso_scale=_baseline(features)
    raw_flex=[]
    raw_drop=[]
    for feature in features:
        if feature["measured"]:
            raw_flex.append(baseline_knee-feature["knee_angle_image_degrees"])
            raw_drop.append((feature["hip_y_pixels"]-baseline_hip)/torso_scale)
        else:
            raw_flex.append(None)
            raw_drop.append(None)
    flex_smooth=_median_without_interpolation(raw_flex)
    hip_smooth=_median_without_interpolation(raw_drop)
    for i,feature in enumerate(features):
        if flex_smooth[i] is not None and hip_smooth[i] is not None:
            feature["flexion_image_degrees"]=round(flex_smooth[i],5)
            feature["hip_descent_torso_units"]=round(hip_smooth[i],6)
            feature["phase"]="standing"
        else:
            feature["phase"]="unavailable"

    phase="standing"
    entry=None
    bottom_streak=0
    peak_flex=-float("inf")
    peak_drop=-float("inf")
    peak_frame=None
    reps=[]
    incomplete=0
    for i,feature in enumerate(features):
        flex=flex_smooth[i]
        drop=hip_smooth[i]
        if flex is None or drop is None:
            if phase!="standing":
                incomplete+=1
            phase="standing"
            entry=None
            bottom_streak=0
            continue
        if phase=="standing":
            if flex>=BEGIN_FLEX_DEGREES and drop>=BEGIN_HIP_DROP:
                phase="descending"
                entry=i
                peak_flex=flex
                peak_drop=drop
                peak_frame=i
                bottom_streak=0
        elif phase in ("descending","bottom","ascending"):
            if flex>peak_flex or drop>peak_drop:
                peak_flex=max(peak_flex,flex)
                peak_drop=max(peak_drop,drop)
                peak_frame=i
            if i-entry>MAX_REP_DURATION:
                incomplete+=1
                phase="standing"
                entry=None
                bottom_streak=0
            elif phase=="descending":
                if flex>=BOTTOM_FLEX_DEGREES and drop>=BOTTOM_HIP_DROP:
                    bottom_streak+=1
                    if bottom_streak>=3:
                        phase="bottom"
                else:
                    bottom_streak=0
                if flex<=END_FLEX_DEGREES and drop<=END_HIP_DROP:
                    # A shallow false start returned to upright without deep position.
                    incomplete+=1
                    phase="standing"
                    entry=None
                    bottom_streak=0
            elif phase=="bottom":
                if flex<=peak_flex-12 and drop<=peak_drop-.08:
                    phase="ascending"
            elif phase=="ascending":
                if flex<=END_FLEX_DEGREES and drop<=END_HIP_DROP:
                    if i-entry>=MIN_REP_DURATION and peak_flex>=BOTTOM_FLEX_DEGREES and peak_drop>=BOTTOM_HIP_DROP:
                        reps.append({
                            "number":len(reps)+1,
                            "start_frame":entry,"bottom_frame":peak_frame,"end_frame":i,
                            "start_seconds":round(entry/FPS,6),
                            "bottom_seconds":round(peak_frame/FPS,6),
                            "end_seconds":round(i/FPS,6),
                            "duration_seconds":round((i-entry)/FPS,6),
                            "peak_estimated_knee_flexion_degrees":round(peak_flex,3),
                            "peak_hip_descent_torso_units":round(peak_drop,4),
                            "classification":"2d_candidate_requires_human_review",
                        })
                    else:
                        incomplete+=1
                    phase="standing"
                    entry=None
                    bottom_streak=0
        feature["phase"]=phase

    if phase!="standing":
        incomplete+=1
    valid=sum(bool(feature["measured"]) for feature in features)
    smoothed=sum(feature["flexion_image_degrees"] is not None for feature in features)
    return {
        "schema":"kinelab.2d-squat-candidates.v1",
        "algorithm_version":SQUAT_ALGORITHM_VERSION,
        "classification":"UNVALIDATED_2D_SQUAT_CANDIDATES",
        "status":"CANDIDATES_PENDING_HUMAN_REVIEW" if reps else "NO_SQUAT_CANDIDATES",
        "role":role,"source_sha256":source_sha256,"test_only":True,
        "activity_assumption":"operator_confirmed_squat",
        "camera_view_assumption":camera_view,
        "observed_frames":len(frames),"fps":FPS,"image_size":[image_width,image_height],
        "candidate_repetition_count":len(reps),
        "repetitions":reps,"incomplete_attempts":incomplete,
        "baseline":{
            "first_frames_required":BASELINE_FRAMES,
            "standing_knee_angle_image_degrees":round(baseline_knee,5),
            "standing_hip_y_pixels":round(baseline_hip,5),
            "standing_torso_scale_pixels":round(torso_scale,5),
        },
        "quality":{
            "complete_required_pose_frames":valid,
            "missing_required_pose_frames":len(frames)-valid,
            "usable_smoothed_frames":smoothed,
            "usable_smoothed_fraction":smoothed/len(frames),
        },
        "count_is_clinically_validated":False,
        "score_interpretation":"Raw model score, not a probability; .43 is a heuristic threshold only.",
        "knee_angle_interpretation":"2D image-plane joint-angle estimate, NOT true sagittal-plane physical ROM.",
        "hip_depth_interpretation":"Normalized pelvis image displacement relative to standing torso pixels, NOT meters.",
        "frame_features":features,
        "phases_present":sorted({f["phase"] for f in features}),
        "limitations":[
            "Only operator-confirmed side-view squat footage; no automatic exercise recognition.",
            "Full valid first-standing baseline and bilateral keypoints required; missing samples abort active reps.",
            "No 3D calibration, anatomy/kinematic ground truth, diagnosis or treatment recommendation.",
            "Manual event review needed before accepting any repetition count.",
        ],
    }


def make_manual_rep_reference(result,labels,*,reviewer,confirmed):
    require(isinstance(result,dict) and result.get("schema")=="kinelab.2d-squat-candidates.v1"
            and result.get("test_only") is True,
            "Invalid 2D squat detector result")
    require(isinstance(reviewer,str) and 2<=len(reviewer.strip())<=90,
            "Manually observed repetitions require named reviewer")
    require(confirmed is True,"Explicit manual video-frame review confirmation required")
    require(isinstance(labels,list) and 1<=len(labels)<=500,
            "Manual reference requires actual reviewed squat repetitions")
    cleaned=[]
    known=set()
    for label in labels:
        require(isinstance(label,dict),"Invalid manually observed squat")
        start,bottom,end=(label.get(k) for k in ("start_frame","bottom_frame","end_frame"))
        require(all(type(x) is int for x in (start,bottom,end)) and
                0<=start<bottom<end<result["observed_frames"],
                "Manual squat sequence must be start < bottom < end within source frames")
        key=(start,bottom,end)
        require(key not in known,"Duplicate manual squat reference")
        known.add(key)
        cleaned.append({"start_frame":start,"bottom_frame":bottom,"end_frame":end})
    cleaned.sort(key=lambda x:x["start_frame"])
    for earlier,later in zip(cleaned,cleaned[1:]):
        require(earlier["end_frame"]<later["start_frame"],
                "Manually reviewed squat repetitions cannot overlap")
    return {
        "schema":"kinelab.manual-2d-squat-reference.v1",
        "status":"HUMAN_OBSERVED_UNINSTRUMENTED_REFERENCE",
        "test_only":True,"source_sha256":result["source_sha256"],
        "role":result["role"],"frames":result["observed_frames"],
        "algorithm_version":result["algorithm_version"],
        "reviewer":reviewer.strip(),"operator_confirmed":True,
        "annotation_origin":"human_video_frame_review",
        "clinical_accuracy_validated":False,
        "recorded_at_utc":datetime.now(timezone.utc).isoformat(),
        "repetitions":cleaned,
    }


def compare_manual_reps(result,reference,tolerance_frames=3):
    require(type(tolerance_frames) is int and 0<=tolerance_frames<=15,
            "Manual timing tolerance is invalid")
    require(isinstance(result,dict) and result.get("schema")=="kinelab.2d-squat-candidates.v1"
            and result.get("test_only") is True,
            "Unrecognized 2D squat candidate report")
    candidates=result["repetitions"]
    if reference is None:
        return {
            "status":"NO_HUMAN_REFERENCE","reference_count":0,
            "candidate_count":len(candidates),"matched_count":0,
            "precision":None,"recall":None,
            "clinical_accuracy_validated":False,
        }
    require(isinstance(reference,dict) and
            reference.get("schema")=="kinelab.manual-2d-squat-reference.v1" and
            reference.get("status")=="HUMAN_OBSERVED_UNINSTRUMENTED_REFERENCE" and
            reference.get("test_only") is True and
            reference.get("role")==result["role"] and
            reference.get("source_sha256")==result["source_sha256"] and
            reference.get("algorithm_version")==result["algorithm_version"] and
            reference.get("frames")==result["observed_frames"] and
            reference.get("annotation_origin")=="human_video_frame_review" and
            reference.get("operator_confirmed") is True and
            reference.get("clinical_accuracy_validated") is False and
            isinstance(reference.get("reviewer"),str) and len(reference["reviewer"].strip())>=2,
            "Manual reference belongs to a different, unconfirmed or falsely validated recording")
    refs=reference.get("repetitions")
    require(isinstance(refs,list) and 1<=len(refs)<=500,"Invalid human reference records")
    observed=set()
    for mark in refs:
        require(isinstance(mark,dict),"Malformed human rep")
        start,bottom,end=(mark.get(k) for k in ("start_frame","bottom_frame","end_frame"))
        require(all(type(n) is int for n in (start,bottom,end)) and
                0<=start<bottom<end<result["observed_frames"] and
                (start,bottom,end) not in observed,
                "Human reference frames invalid or duplicated")
        observed.add((start,bottom,end))
    ordered=sorted(refs,key=lambda mark:mark["start_frame"])
    for first,second in zip(ordered,ordered[1:]):
        require(first["end_frame"]<second["start_frame"],
                "Manual observed squat repetitions overlap; cannot score this reference")
    options=[]
    for i,ref in enumerate(refs):
        for j,pred in enumerate(candidates):
            dist=abs(ref["bottom_frame"]-pred["bottom_frame"])
            if dist<=tolerance_frames:
                options.append((dist,i,j))
    used_r,used_p=set(),set()
    errors=[]
    for dist,i,j in sorted(options):
        if i in used_r or j in used_p:
            continue
        used_r.add(i);used_p.add(j);errors.append(dist)
    return {
        "status":"EXPLORATORY_HUMAN_AGREEMENT_ONLY",
        "reference_count":len(refs),"candidate_count":len(candidates),
        "matched_count":len(errors),
        "precision":len(errors)/len(candidates) if candidates else None,
        "recall":len(errors)/len(refs),
        "absolute_bottom_frame_errors":errors,
        "tolerance_frames":tolerance_frames,
        "clinical_accuracy_validated":False,
        "interpretation":"Manual video annotation agreement, not instrumented or clinical squat accuracy.",
    }
