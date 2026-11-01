"""TEST_ONLY mounted immediate-stop checks. Reuses the owned isolation fixture."""
import argparse
import json
from pathlib import Path

from tools.verify_browser_isolation import _prepare_default_comparison_fixture, verify


def run_checks(browser, evaluate, wait_for, service, output, checks, reopen):
    def activate(label, *, scope="document", key="Enter"):
        label_js = json.dumps(label)
        root = "document.querySelector('dialog[open]')" if scope == "dialog" else "document"
        target = f"(() => {{const root={root};const a=document.activeElement;return !!root&&root.contains(a)&&a?.tagName==='BUTTON'&&a.textContent.trim()==={label_js}&&!a.disabled;}})()"
        for _ in range(80):
            if evaluate(target):
                browser("press", key)
                return
            browser("press", "Shift+Tab")
        raise AssertionError("Native keyboard cannot reach enabled " + label)

    def setup():
        wait_for("!!document.querySelector('.uw-live-studio')")
        evaluate("window.__stopErrors=[];window.addEventListener('error',e=>window.__stopErrors.push(e.message));window.addEventListener('unhandledrejection',()=>window.__stopErrors.push('unhandledrejection'));")
        activate("Feed: REAL CAMERA")
        wait_for("document.body.textContent.includes('SYNTHETIC TEST ONLY')")
        assert evaluate("window.__cameraRequests===0")

    def gate(suffix):
        evaluate("""(() => {
 const original=window.fetch.bind(window);window.__stopGate={held:false,release:null};
 window.fetch=async(input,options)=>{
  const response=await original(input,options);
  if(options?.method==='POST'&&String(input).endsWith(SUFFIX)&&!window.__stopGate.held){
   window.__stopGate.held=true;await new Promise(resolve=>{window.__stopGate.release=resolve;});
  }
  return response;
 };
})()""".replace("SUFFIX", json.dumps(suffix)))

    def release():
        evaluate("window.__stopGate?.release?.()")

    def counters():
        return evaluate(r"""(() => {const t=document.querySelector('[data-recording-saved]')?.textContent||'';
 const m=t.match(/Saved through frame (\d+) \/ produced (\d+)\. Pending: (\d+)/);
 if(!m)throw Error('Explicit saved/produced/pending text missing');return m.slice(1).map(Number);})()""")

    def clean_page():
        assert evaluate("window.__cameraRequests===0"), "Synthetic acceptance must never request a camera"
        assert evaluate("window.__stopErrors.length===0"), "Page errors must remain absent"

    def stopped_latched():
        assert evaluate("document.querySelector('.uw-live-studio').dataset.activityStopped==='true'")
        assert evaluate("document.body.textContent.includes('Activity stopped. Follow the owner-approved protocol')")
        assert evaluate("[...document.querySelectorAll('button')].filter(b=>['Pause tracking','Resume tracking'].includes(b.textContent.trim())).every(b=>b.disabled)")
        assert evaluate("window.__cameraRequests===0"), "A feed change after Stop must never request a camera"

    def feed_round_trip(name, sid, saved, state):
        """Switch feed both ways with native keys after Stop; the mount latch must hold."""
        enabled = evaluate("""new Promise(resolve=>{let n=0;const t=setInterval(()=>{
 const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='Feed: SYNTHETIC TEST');
 if((b&&!b.disabled)||++n>=40){clearInterval(t);resolve(!!b&&!b.disabled);}},50);})""")
        if not enabled:
            checks[name] = "LIMITATION_FEED_DISABLED_NOT_EXERCISED"
            raise AssertionError(name + ": enabled Feed: SYNTHETIC TEST unavailable after Stop; case not exercised")
        rows_before = service.recordings.list_recordings()
        verified_before = service.recordings.verify(sid) if state == "FINALIZED" else None
        activate("Feed: SYNTHETIC TEST")
        wait_for("!!document.querySelector('.uw-pose-status')&&!document.querySelector('[aria-label=\"Synthetic recording\"]')")
        assert evaluate("document.body.textContent.includes('local image-plane inference; physical accuracy UNVERIFIED')")
        stopped_latched()
        assert evaluate("document.querySelector('.uw-pose-status strong')?.textContent==='UNAVAILABLE'&&document.querySelector('.uw-pose-status').textContent.includes('ACTIVITY_STOPPED')")
        assert evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Start local camera')?.disabled===true")
        activate("Feed: REAL CAMERA")
        wait_for("!!document.querySelector('[aria-label=\"Synthetic recording\"]')&&!document.querySelector('.uw-pose-status')")
        assert evaluate("document.body.textContent.includes('SYNTHETIC TEST ONLY')")
        stopped_latched()
        assert evaluate("[...document.querySelectorAll('button')].find(b=>b.textContent.trim()==='Record synthetic test')?.disabled===true")
        evaluate("new Promise(resolve=>setTimeout(resolve,250))")
        stopped_latched()
        assert service.recordings.list_recordings() == rows_before, "Feed changes must not create or advance a recording"
        row = next(r for r in rows_before if r["session_id"] == sid)
        assert row["state"] == state and row["saved_through"] == saved
        if verified_before is not None:
            assert service.recordings.verify(sid) == verified_before, "Finalized prefix must stay unchanged"
        clean_page()
        checks[name] = True

    setup()
    gate("/recordings")
    try:
        activate("Record synthetic test", key="Space")
        wait_for("window.__stopGate.held")
        activate("Stop activity")
        assert evaluate("document.querySelector('.uw-live-studio').dataset.activityStopped==='true'")
    finally:
        release()
    wait_for("document.body.textContent.includes('no frames finalized')")
    rows = service.recordings.list_recordings()
    assert len(rows) == 1 and rows[0]["source_kind"] == "synthetic" and rows[0]["saved_through"] == 0
    assert rows[0]["state"] == "RECORDING", "Empty stopped draft must not claim finalization"
    clean_page()
    checks["stop_pending_create_no_late_restart"] = True
    feed_round_trip("stop_empty_feed_switch_cannot_reopen", rows[0]["session_id"], 0, "RECORDING")

    reopen()
    setup()
    before_ids = {row["session_id"] for row in service.recordings.list_recordings()}
    activate("Record synthetic test", key="Space")
    wait_for("Number(document.querySelector('[data-recording-saved]')?.dataset.recordingSaved)>=16")
    sid = next(row["session_id"] for row in service.recordings.list_recordings() if row["session_id"] not in before_ids)
    gate("/chunks")
    try:
        wait_for("window.__stopGate.held")
        activate("Stop activity")
        frozen = counters()
        assert frozen[2] > 0, "The stopped case must actually contain unacknowledged frames"
        assert evaluate("document.querySelector('.uw-live-studio').dataset.activityStopped==='true'")
        evaluate("new Promise(resolve=>setTimeout(resolve,250))")
        assert counters() == frozen, "Stopping freezes production and cannot invent an ACK"
    finally:
        release()
    wait_for("document.body.textContent.includes('Synthetic recording finalized')")
    final = service.recordings.verify(sid)
    assert final["state"] == "FINALIZED" and final["saved_through"] == frozen[1]
    assert final["manifest"]["end_reason"] == "capture_interrupted"
    assert counters() == [frozen[1], frozen[1], 0]
    clean_page()
    checks["stop_pending_chunk_retains_and_finalizes_exact_prefix"] = frozen[1]
    feed_round_trip("stop_finalized_feed_switch_cannot_reopen", sid, frozen[1], "FINALIZED")

    reopen()
    setup()
    activate("Finish Synthetic Set")
    wait_for("!!document.querySelector('dialog[open]')")
    activate("Stop activity", scope="dialog", key="Space")
    assert evaluate("!!document.querySelector('dialog[open]')"), "Stop must preserve dialog semantics"
    assert evaluate("[...document.querySelectorAll('dialog button')].find(b=>b.textContent.trim()==='Start New Set')?.disabled===true")
    browser("press", "Escape")
    assert evaluate("!document.querySelector('dialog[open]')")
    assert evaluate("document.activeElement?.textContent.trim()==='Finish Synthetic Set'"), "Native Escape must retain focus return"
    clean_page()
    checks["stop_inside_modal_native_keyboard_no_restart"] = True
    browser("screenshot", str(output / "synthetic-activity-stopped.png"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--frontend-dist", type=Path, required=True)
    parser.add_argument("--agent-browser-executable", type=Path, required=True)
    parser.add_argument("--agent-browser-sha256", required=True)
    args = parser.parse_args()
    result = verify(args.output, scenario=run_checks, fixture=_prepare_default_comparison_fixture,
                    frontend_dist=args.frontend_dist, agent_browser_executable=args.agent_browser_executable,
                    agent_browser_sha256=args.agent_browser_sha256)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
