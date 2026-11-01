"""Tests first: bounded 2D squat phase/rep proposals, never real clinical accuracy."""
import copy
import unittest

from squat_events import (
    SQUAT_ALGORITHM_VERSION,
    SquatEvidenceError,
    analyze_squats,
    compare_manual_reps,
    make_manual_rep_reference,
)

ROLE = "cam01_trial"
HASH = "a" * 64

def record(frame, bend=0., drop=0., threshold=1.0, people=1):
    """Synthetic side-view standing and squat, in arbitrary image pixels."""
    points = [[100., 90.] for _ in range(26)]
    scores = [0.91]*26
    for dx,sh,hi,kn,an in ((0.,5,11,13,15),(130.,6,12,14,16)):
        points[sh] = [100.+dx, 60.+drop*40.]
        points[hi] = [100.+dx, 100.+drop*40.]
        points[kn] = [100.+dx+bend*.70, 150.+drop*20.]
        points[an] = [100.+dx,205.]
        scores[sh]=scores[hi]=scores[kn]=scores[an]=threshold
    return {
        "frame_index":frame, "time_seconds":round(frame/30.,6),
        "people_detected":people, "selected_person_index":0 if people else None,
        "xy_pixels":points if people else None,
        "confidence":scores if people else None,
    }

def video(movements):
    return {
        "schema":"kinelab.testonly.fullseq.halpe26.v1","test_only":True,
        "role":ROLE,"source_sha256":HASH,"fps":30,
        "model_score_threshold":.43,
        "coordinates":"unscaled source-video 2D image pixels; not meters",
        "frames":[record(i,bend,drop) for i,(bend,drop) in enumerate(movements)],
    }

def single_squat():
    poses = [(0.,0.)]*25
    poses += [(60.*i/19,.62*i/19) for i in range(20)]
    poses += [(60.,.62)]*7
    poses += [(60.*(1-i/19),.62*(1-i/19)) for i in range(20)]
    poses += [(0.,0.)]*25
    return poses

def fixture_reps(n=3):
    return video([(0.,0.)]*25 + single_squat()*n + [(0.,0.)]*10)

def run(source,**overrides):
    return analyze_squats(source,ROLE,HASH,camera_view="side",
                          activity_confirmed=True, image_width=1024,
                          image_height=576, **overrides)

class SquatTests(unittest.TestCase):
    def test_three_synthetic_squats_detect_complete_repetitions_with_phases(self):
        result=run(fixture_reps(3))
        self.assertEqual(result["schema"],"kinelab.2d-squat-candidates.v1")
        self.assertEqual(result["algorithm_version"],SQUAT_ALGORITHM_VERSION)
        self.assertEqual(result["classification"],"UNVALIDATED_2D_SQUAT_CANDIDATES")
        self.assertEqual(result["candidate_repetition_count"],3)
        self.assertEqual([r["number"] for r in result["repetitions"]],[1,2,3])
        for rep in result["repetitions"]:
            self.assertLess(rep["start_frame"],rep["bottom_frame"])
            self.assertLess(rep["bottom_frame"],rep["end_frame"])
            self.assertGreater(rep["peak_hip_descent_torso_units"],.35)
            self.assertTrue(rep["peak_estimated_knee_flexion_degrees"]>45)
            self.assertGreater(rep["duration_seconds"],.7)
            self.assertEqual(rep["classification"],"2d_candidate_requires_human_review")
        self.assertEqual(result["count_is_clinically_validated"],False)
        self.assertIn("descending",result["phases_present"])
        self.assertIn("bottom",result["phases_present"])
        self.assertIn("ascending",result["phases_present"])

    def test_static_standing_never_creates_a_repetition(self):
        result=run(video([(0.,0.)]*240))
        self.assertEqual(result["candidate_repetition_count"],0)
        self.assertEqual(result["status"],"NO_SQUAT_CANDIDATES")
        self.assertEqual(result["observed_frames"],240)

    def test_walking_knee_flexion_alone_does_not_meet_hip_depth_gate(self):
        sequence=[(45. if i%40<20 else 0., .02) for i in range(240)]
        sequence[:25]=[(0.,0.)]*25
        result=run(video(sequence))
        self.assertEqual(result["candidate_repetition_count"],0)

    def test_partial_descent_never_counts_as_completed_squat(self):
        moves=[(0.,0.)]*28+[(60.*i/19,.62*i/19) for i in range(20)]+[(60.,.62)]*30
        result=run(video(moves))
        self.assertEqual(result["candidate_repetition_count"],0)
        self.assertGreaterEqual(result["incomplete_attempts"],1)

    def test_missing_ankle_during_ascent_aborts_not_bridges_rep(self):
        source=fixture_reps(1)
        for i in range(65,76):
            source["frames"][i]["confidence"][16]=.1
        result=run(source)
        self.assertEqual(result["candidate_repetition_count"],0)
        self.assertGreaterEqual(result["incomplete_attempts"],1)
        self.assertTrue(all(result["frame_features"][i]["phase"]=="unavailable" for i in range(65,76)))

    def test_short_weak_motion_never_counts(self):
        moves=[(0.,0.)]*25
        moves += [(10.*i/15,.08*i/15) for i in range(16)]
        moves += [(10.*(1-i/15),.08*(1-i/15)) for i in range(16)]
        moves += [(0.,0.)]*35
        self.assertEqual(run(video(moves))["candidate_repetition_count"],0)

    def test_baseline_must_begin_with_stable_extended_posture(self):
        source=video([(58.,.55)]*28+single_squat())
        with self.assertRaisesRegex(SquatEvidenceError,"standing|baseline"):
            run(source)

    def test_unconfirmed_activity_or_frontal_view_cannot_run(self):
        source=fixture_reps(1)
        with self.assertRaisesRegex(SquatEvidenceError,"activity"):
            analyze_squats(source,ROLE,HASH,camera_view="side",activity_confirmed=False,
                           image_width=1024,image_height=576)
        with self.assertRaisesRegex(SquatEvidenceError,"side"):
            analyze_squats(source,ROLE,HASH,camera_view="front",activity_confirmed=True,
                           image_width=1024,image_height=576)

    def test_metadata_changed_source_and_invalid_frames_are_rejected(self):
        src=fixture_reps(1)
        for action in [
            lambda x:x.update({"test_only":False}),
            lambda x:x.update({"source_sha256":"b"*64}),
            lambda x:x.update({"fps":60}),
            lambda x:x["frames"].__setitem__(17,x["frames"][16]),
            lambda x:x["frames"][30].update({"xy_pixels":[[0.,0.]]}),
            lambda x:x["frames"][30].update({"people_detected":-1}),
        ]:
            bad=copy.deepcopy(src)
            action(bad)
            with self.subTest(action=action),self.assertRaises(SquatEvidenceError):
                run(bad)

    def test_model_scores_above_one_are_not_probabilities(self):
        src=fixture_reps(1)
        for frame in src["frames"]:
            frame["confidence"][13]=1.08
            frame["confidence"][14]=1.10
        result=run(src)
        self.assertEqual(result["candidate_repetition_count"],1)
        self.assertIn("not",result["score_interpretation"].lower())
        self.assertFalse(result["count_is_clinically_validated"])

    def test_empty_fidelity_or_loss_of_both_sides_never_creates_fake_angles(self):
        src=fixture_reps(1)
        for i in range(85,100):
            for joint in (13,14):
                src["frames"][i]["confidence"][joint]=.15
        result=run(src)
        self.assertEqual(result["candidate_repetition_count"],0)
        self.assertGreater(result["quality"]["missing_required_pose_frames"],0)
        self.assertTrue(all(result["frame_features"][i]["knee_angle_image_degrees"] is None
                            for i in range(85,100)))

    def test_manual_comparison_not_populated_without_reference(self):
        result=run(fixture_reps(1))
        score=compare_manual_reps(result,None)
        self.assertIsNone(score["precision"])
        self.assertIsNone(score["recall"])
        self.assertEqual(score["status"],"NO_HUMAN_REFERENCE")
        self.assertEqual(score["matched_count"],0)

    def test_manual_reference_requires_confirmed_named_observer(self):
        result=run(fixture_reps(1))
        rep=result["repetitions"][0]
        labels=[{"start_frame":rep["start_frame"],"bottom_frame":rep["bottom_frame"],
                 "end_frame":rep["end_frame"]}]
        with self.assertRaises(SquatEvidenceError):
            make_manual_rep_reference(result,labels,reviewer="",confirmed=True)
        with self.assertRaises(SquatEvidenceError):
            make_manual_rep_reference(result,labels,reviewer="PT observer",confirmed=False)
        ref=make_manual_rep_reference(result,labels,reviewer="PT observer",confirmed=True)
        self.assertFalse(ref["clinical_accuracy_validated"])
        self.assertTrue(ref["operator_confirmed"])
        self.assertEqual(ref["source_sha256"],HASH)
        score=compare_manual_reps(result,ref,tolerance_frames=3)
        self.assertEqual(score["matched_count"],1)
        self.assertEqual(score["status"],"EXPLORATORY_HUMAN_AGREEMENT_ONLY")
        self.assertEqual(score["recall"],1.)

    def test_forged_human_reference_flags_and_overlap_are_rejected(self):
        result=run(fixture_reps(2))
        a,b=result["repetitions"]
        ref=make_manual_rep_reference(result,[
            {"start_frame":a["start_frame"],"bottom_frame":a["bottom_frame"],"end_frame":a["end_frame"]},
            {"start_frame":b["start_frame"],"bottom_frame":b["bottom_frame"],"end_frame":b["end_frame"]},
        ],reviewer="reviewer",confirmed=True)
        altered=[
            {"clinical_accuracy_validated":True},
            {"status":"CLINICAL_ACCURACY_VALIDATED"},
            {"annotation_origin":"automatic"},
            {"operator_confirmed":False},
            {"reviewer":""},
            {"algorithm_version":"not-our-algorithm"},
            {"repetitions":[ref["repetitions"][0],ref["repetitions"][0]]},
            {"repetitions":[
                ref["repetitions"][0],
                {**ref["repetitions"][1],"start_frame":ref["repetitions"][0]["end_frame"]-1},
            ]},
        ]
        for patch in altered:
            with self.subTest(patch=patch),self.assertRaises(SquatEvidenceError):
                compare_manual_reps(result,{**ref,**patch})

    def test_foreign_reference_duplicate_and_wrong_manual_frames_rejected(self):
        result=run(fixture_reps(1))
        rep=result["repetitions"][0]
        label={"start_frame":rep["start_frame"],"bottom_frame":rep["bottom_frame"],
               "end_frame":rep["end_frame"]}
        for wrong in [[label,label],[{"start_frame":48,"bottom_frame":42,"end_frame":85}],
                      [{"start_frame":50,"bottom_frame":60,"end_frame":50000}]]:
            with self.assertRaises(SquatEvidenceError):
                make_manual_rep_reference(result,wrong,reviewer="PT",confirmed=True)
        ref=make_manual_rep_reference(result,[label],reviewer="PT",confirmed=True)
        with self.assertRaises(SquatEvidenceError):
            compare_manual_reps(result,{**ref,"source_sha256":"b"*64})
        with self.assertRaises(SquatEvidenceError):
            compare_manual_reps(result,ref,tolerance_frames=-1)

if __name__=="__main__":
    unittest.main()
