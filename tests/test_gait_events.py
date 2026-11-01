"""T5 gait event *candidates* on isolated 2D imagery, pending manual reference."""
import copy
import math
import unittest

from gait_events import (
    GAIT_ALGORITHM_VERSION,
    GaitEvidenceError,
    make_manual_reference,
    orient_event_candidates,
    propose_extrema,
    score_manual_reference,
    validate_2d_trajectories,
)

HASH="a"*64
ROLE="cam01_trial"

def fixture(n=240, period=40, missing=()):
    frames=[]
    for i in range(n):
        points=[[255.,190.] for _ in range(26)]
        scores=[.92]*26
        phase=2*math.pi*i/period
        points[19]=[300.,320.]
        points[24]=[300+26*math.sin(phase),460.]
        points[20]=[300+22*math.sin(phase-math.pi/2),468.]
        points[25]=[300+26*math.sin(phase+math.pi),461.]
        points[21]=[300+22*math.sin(phase+math.pi/2),466.]
        if i in missing:
            scores[24]=.10
        frames.append({"frame_index":i,"time_seconds":round(i/30,6),
                       "people_detected":1,"selected_person_index":0,
                       "xy_pixels":points,"confidence":scores})
    return {"schema":"kinelab.testonly.fullseq.halpe26.v1",
            "test_only":True,"role":ROLE,"fps":30,
            "source_sha256":HASH, "model_score_threshold":.43,
            "coordinates":"unscaled source-video 2D image pixels; not meters",
            "frames":frames}

class GaitEventTests(unittest.TestCase):
    def test_first_validate_rejects_wrong_scope_hash_frame_or_person(self):
        original=fixture()
        self.assertEqual(len(validate_2d_trajectories(original,ROLE,HASH)),240)
        cases=[
            lambda x:x.update({"test_only":False}),
            lambda x:x.update({"source_sha256":"b"*64}),
            lambda x:x.update({"role":"cam02_trial"}),
            lambda x:x.update({"fps":24}),
            lambda x:x["frames"].__setitem__(3,x["frames"][1]),
            lambda x:x["frames"][10].update({"time_seconds":60}),
            lambda x:x["frames"][0].update({"confidence":[1,2]}),
            lambda x:x["frames"][0].update({"xy_pixels":None}),
        ]
        for mutate in cases:
            test=copy.deepcopy(original);mutate(test)
            with self.subTest(mutate=mutate),self.assertRaises(GaitEvidenceError):
                validate_2d_trajectories(test,ROLE,HASH)

    def test_candidate_events_are_only_extrema_without_screen_orientation(self):
        result=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        self.assertEqual(result["schema"],"kinelab.2d-gait-candidates.v1")
        self.assertEqual(result["algorithm_version"],GAIT_ALGORITHM_VERSION)
        self.assertEqual(result["classification"],"UNVALIDATED_EVENT_CANDIDATES")
        self.assertGreater(len(result["candidates"]),10)
        self.assertEqual(result["observed_frames"],240)
        self.assertEqual(result["frames_with_required_hip_and_both_feet"],240)
        self.assertTrue(all(c["event_type"]=="unassigned_extremum" for c in result["candidates"]))
        self.assertTrue(all(c["side"] in ("left","right") and c["foot_point"] in ("heel","big_toe") for c in result["candidates"]))
        self.assertTrue(all(0<=c["frame_index"]<240 for c in result["candidates"]))
        self.assertTrue(all(c["method"]=="image-x-relative-to-hip" for c in result["candidates"]))

    def test_fixed_foot_or_tiny_motion_avoids_fabricated_steps(self):
        data=fixture(n=160)
        for f in data["frames"]:
            for idx in (20,21,24,25):
                f["xy_pixels"][idx][0]=300.
        res=propose_extrema(data,ROLE,HASH,image_width=1024,image_height=576)
        self.assertEqual(len(res["candidates"]),0)
        self.assertFalse(res["has_manually_validated_events"])

    def test_missing_keypoints_break_signal_segments_without_interpolating(self):
        missing=set(range(48,84))
        data=fixture(n=200,missing=missing)
        res=propose_extrema(data,ROLE,HASH,image_width=1024,image_height=576)
        self.assertEqual(res["required_landmark_coverage"]["left_heel"],(200-36)/200)
        self.assertFalse(any(c["foot_point"]=="heel" and c["side"]=="left" and 45<=c["frame_index"]<=86
                             for c in res["candidates"]))
        self.assertTrue(all(not c.get("interpolated",False) for c in res["candidates"]))

    def test_orientation_is_explicit_and_inevitably_provisional(self):
        base=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        right=orient_event_candidates(base,screen_forward="right")
        left=orient_event_candidates(base,screen_forward="left")
        r=[c for c in right["candidates"] if c["foot_point"]=="heel" and c["extremum"]=="max"]
        l=[c for c in left["candidates"] if c["foot_point"]=="heel" and c["extremum"]=="max"]
        self.assertGreater(len(r),0)
        self.assertEqual({c["event_type"] for c in r},{"candidate_initial_contact"})
        self.assertEqual({c["event_type"] for c in l},{"unassigned_extremum"})
        self.assertEqual(right["screen_forward"],"right")
        self.assertEqual(right["manual_validation_status"],"not_reviewed")
        with self.assertRaises(GaitEvidenceError):
            orient_event_candidates(base,screen_forward="unknown")

    def test_manual_reference_requires_actual_operator_labels_and_source(self):
        evidence=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        labels=[
            {"frame_index":50,"side":"left","event_type":"initial_contact"},
            {"frame_index":69,"side":"left","event_type":"toe_off"},
        ]
        ref=make_manual_reference(evidence,labels,reviewer="PT test reviewer",
                                  confirmed=True)
        self.assertEqual(ref["annotation_origin"],"human_observed_video_frames")
        self.assertEqual(ref["source_sha256"],HASH)
        self.assertEqual(ref["status"],"MANUAL_OBSERVATIONS_NOT_CLINICAL_GROUND_TRUTH")
        self.assertEqual(len(ref["labels"]),2)
        for wrong in [
            {"reviewer": "", "confirmed": True},
            {"reviewer": "PT", "confirmed": False},
        ]:
            with self.assertRaises(GaitEvidenceError):
                make_manual_reference(evidence,labels,**wrong)
        with self.assertRaises(GaitEvidenceError):
            make_manual_reference(evidence,[],reviewer="PT",confirmed=True)
        with self.assertRaises(GaitEvidenceError):
            make_manual_reference(evidence,[labels[0],labels[0]],reviewer="PT",confirmed=True)

    def test_manual_match_is_one_to_one_no_false_perfect_score(self):
        evidence=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        oriented=orient_event_candidates(evidence,screen_forward="right")
        first=next(c for c in oriented["candidates"] if c["event_type"]=="candidate_initial_contact")
        labels=[{"frame_index":first["frame_index"],"side":first["side"],"event_type":"initial_contact"}]
        reference=make_manual_reference(evidence,labels,reviewer="tester",confirmed=True)
        outcome=score_manual_reference(oriented,reference,tolerance_frames=3)
        self.assertEqual(outcome["matched_count"],1)
        self.assertEqual(outcome["reference_count"],1)
        self.assertGreaterEqual(outcome["candidate_count"],1)
        self.assertNotEqual(outcome["status"],"CLINICAL_ACCURACY_VALIDATED")
        self.assertTrue(all(v>=0 for v in outcome["absolute_frame_errors"]))
        self.assertEqual(outcome["tolerance_frames"],3)

    def test_no_manual_labels_yields_unvalidated_not_100_percent(self):
        evidence=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        oriented=orient_event_candidates(evidence,screen_forward="right")
        outcome=score_manual_reference(oriented,None,tolerance_frames=3)
        self.assertEqual(outcome["status"],"NO_MANUAL_REFERENCE")
        self.assertIsNone(outcome["precision"])
        self.assertIsNone(outcome["recall"])
        self.assertEqual(outcome["matched_count"],0)

    def test_scoring_rejects_unreviewed_or_modified_reference_contract(self):
        base=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        oriented=orient_event_candidates(base,screen_forward="right")
        manual=make_manual_reference(base,[
            {"frame_index":40,"side":"left","event_type":"initial_contact"},
        ],reviewer="test reviewer",confirmed=True)
        self.assertFalse(manual["algorithm_events_shown_during_annotation"])
        self.assertFalse(manual["clinical_accuracy_validated"])
        changes=[
            {"status":"CLINICAL_ACCURACY_VALIDATED"},
            {"reviewer":""},
            {"operator_confirmed":False},
            {"algorithm_events_shown_during_annotation":True},
            {"clinical_accuracy_validated":True},
            {"fps":60},
            {"frames":99},
            {"annotation_origin":"auto-generated"},
            {"labels":[manual["labels"][0],manual["labels"][0]]},
            {"labels":[{**manual["labels"][0],"time_seconds":100.0}]},
        ]
        for bad in changes:
            with self.subTest(bad=bad),self.assertRaises(GaitEvidenceError):
                score_manual_reference(oriented,{**manual,**bad})

    def test_candidates_never_claim_stride_length_or_clinical_cadence(self):
        result=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        for forbidden in ("cadence_spm","stride_length_m","clinical_gait_accuracy","patient_id"):
            self.assertNotIn(forbidden,result)

    def test_foreign_reference_and_invalid_tolerance_rejected(self):
        evidence=propose_extrema(fixture(),ROLE,HASH,image_width=1024,image_height=576)
        oriented=orient_event_candidates(evidence,screen_forward="right")
        ref=make_manual_reference(evidence,[{"frame_index":54,"side":"left","event_type":"initial_contact"}],
                                  reviewer="PT",confirmed=True)
        wrong=dict(ref,source_sha256="f"*64)
        with self.assertRaises(GaitEvidenceError):
            score_manual_reference(oriented,wrong)
        with self.assertRaises(GaitEvidenceError):
            score_manual_reference(oriented,ref,tolerance_frames=-1)

if __name__=="__main__":
    unittest.main()
