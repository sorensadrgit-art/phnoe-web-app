"""Generated-fixture recording fault/limit checks; no camera or participant access."""
def run_checks(browser, evaluate, wait_for, service, output, checks, reopen, case):
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Feed: REAL CAMERA", "--exact")
    wait_for("document.body.textContent.includes('SYNTHETIC TEST ONLY')")
    if case in {"empty-start", "retry-clock"}:
        evaluate("""window.__loseCreate=true;const original=window.fetch;window.fetch=async(...args)=>{
 const create=String(args[0]).endsWith('/recordings')&&args[1]?.method==='POST';
 if(create&&window.__loseCreate){window.__loseCreate=false;
  if(LOST_AFTER_COMMIT)await original(...args);
  throw new TypeError('Synthetic creation response lost');}
 return original(...args);};""".replace("LOST_AFTER_COMMIT", str(case == "retry-clock").lower()))
    if case == "batching":
        evaluate("""window.__chunkSizes=[];const original=window.fetch;window.fetch=async(...args)=>{
 if(String(args[0]).endsWith('/chunks'))window.__chunkSizes.push(JSON.parse(JSON.parse(args[1].body).frames_json).length);
 return original(...args);};""")
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Record synthetic test", "--exact")
    if case in {"empty-start", "retry-clock"}:
        wait_for("document.body.textContent.includes('Synthetic creation response lost')")
    if case == "empty-start":
        browser("snapshot", "-i")
        assert evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Close empty attempt'&&!b.disabled)"), "Failed empty start must have a safe exit"
        browser("find", "role", "button", "click", "--name", "Close empty attempt", "--exact")
        assert evaluate("Array.from(document.querySelectorAll('.uw-nav-link')).every(b=>!b.disabled)")
        assert service.recordings.list_recordings() == []
        checks[case] = "No frames discarded; navigation unlocked"
    else:
        if case == "retry-clock":
            assert len(service.recordings.list_recordings()) == 1
            browser("snapshot", "-i")
            browser("find", "role", "button", "click", "--name", "Retry pending save", "--exact")
        wait_for("Number(document.querySelector('[data-recording-saved]')?.dataset.recordingSaved)>=16")
        rows = service.recordings.list_recordings()
        assert len(rows) == 1
        sid = rows[0]["session_id"]
        if case == "retry-clock":
            first = next(service.recordings.iter_frames(sid))
            assert first["time_ms"] < 1000, first["time_ms"]
        if case == "batching":
            wait_for("Number(document.querySelector('[data-recording-saved]').dataset.recordingSaved)>=60")
        if case == "duration":
            evaluate("const now=performance.now.bind(performance);performance.now=()=>now()+1800001;")
            wait_for("document.body.textContent.includes('Duration limit reached; finalize saved frames')")
            assert not evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Retry pending save')")
        browser("snapshot", "-i")
        browser("find", "role", "button", "click", "--name", "Finalize synthetic recording", "--exact")
        wait_for("document.body.textContent.includes('Synthetic recording finalized')")
        result = service.recordings.verify(sid)
        if case == "batching":
            sizes = evaluate("window.__chunkSizes")
            assert max(sizes) <= 16 and sum(sizes) / len(sizes) >= 5, sizes
            assert sum(sizes) == result["manifest"]["frame_count"]
            checks[case] = {"frames": sum(sizes), "requests": len(sizes)}
        else:
            checks[case] = result["manifest"]["frame_count"]
        assert all(frame["time_ms"] <= 1800000 for frame in service.recordings.iter_frames(sid))
    browser("screenshot", str(output / (case + ".png")))
    assert not browser("errors").get("errors", [])

