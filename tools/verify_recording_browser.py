"""Mounted synthetic recording checks, invoked by verify_browser_isolation --recording."""


def run_checks(browser, evaluate, wait_for, service, output, checks, reopen):
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Feed: REAL CAMERA", "--exact")
    wait_for("document.body.textContent.includes('SYNTHETIC TEST ONLY')")
    browser("snapshot", "-i")
    assert evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent==='Record synthetic test')"), "Durable synthetic recording control missing"
    browser("find", "role", "button", "click", "--name", "Record synthetic test", "--exact")
    wait_for("Number(document.querySelector('[data-recording-saved]')?.dataset.recordingSaved)>=16")
    rows = service.recordings.list_recordings()
    assert len(rows) == 1 and rows[0]["source_kind"] == "synthetic"
    assert rows[0]["header"]["coordinates"]["mirrored"] is False, "Display mirroring must not relabel unmirrored source landmarks"
    sid = rows[0]["session_id"]
    assert evaluate("Array.from(document.querySelectorAll('.uw-nav-link')).filter(b=>b.getAttribute('aria-current')!=='page').every(b=>b.disabled)")
    checks["bounded_synthetic_capture_started"] = sid

    evaluate("""window.__loseAck=true;const original=window.fetch;window.fetch=async(...args)=>{
 const response=await original(...args);
 if(window.__loseAck&&String(args[0]).endsWith('/chunks')){window.__loseAck=false;throw new TypeError('Synthetic lost acknowledgment after commit');}
 return response;};""")
    wait_for("document.body.textContent.includes('Synthetic lost acknowledgment after commit')")
    committed = service.recordings.verify(sid)["saved_through"]
    known = evaluate("Number(document.querySelector('[data-recording-saved]').dataset.recordingSaved)")
    assert committed > known, (committed, known)
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Retry pending save", "--exact")
    wait_for(f"Number(document.querySelector('[data-recording-saved]').dataset.recordingSaved)>={committed}")
    browser("find", "role", "button", "click", "--name", "Finalize synthetic recording", "--exact")
    wait_for("document.body.textContent.includes('Synthetic recording finalized')")
    final = service.recordings.verify(sid)
    assert final["state"] == "FINALIZED" and final["saved_through"] >= committed
    checks["lost_ack_retry_without_duplicate_frames"] = final["manifest"]["frame_count"]
    browser("screenshot", str(output / "synthetic-recording-finalized.png"))

    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Record synthetic test", "--exact")
    wait_for("Number(document.querySelector('[data-recording-saved]').dataset.recordingSaved)>=16 && !document.body.textContent.includes('Synthetic recording finalized')")
    draft = next(row for row in service.recordings.list_recordings() if row["state"] == "RECORDING")
    saved_before_reload = draft["saved_through"]
    reopen()
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Feed: REAL CAMERA", "--exact")
    wait_for("document.body.textContent.includes('Unacknowledged tail: UNKNOWN')")
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Finalize saved prefix", "--exact")
    wait_for("document.body.textContent.includes('Recovered saved prefix')")
    recovered = service.recordings.verify(draft["session_id"])
    assert recovered["saved_through"] >= saved_before_reload
    assert recovered["manifest"]["end_reason"] == "recovered_prefix"
    assert recovered["manifest"]["unacknowledged_tail"] == "UNKNOWN"
    assert service.recordings.verify(sid)["manifest_sha256"] == final["manifest_sha256"]
    checks["restart_recovers_acknowledged_prefix_without_hiding_unknown_tail"] = recovered["saved_through"]
    browser("screenshot", str(output / "synthetic-recovery.png"))

    browser("snapshot", "-i")
    browser("scrollintoview", ".uw-nav-link:has-text('Reports')")
    browser("find", "role", "button", "click", "--name", "Reports Local evidence and exports")
    wait_for("document.body.textContent.includes('Create Backup Archive')")
    evaluate("window.confirm=()=>true")
    browser("snapshot", "-i")
    browser("find", "role", "button", "click", "--name", "Create Backup Archive", "--exact")
    wait_for("document.body.textContent.includes('Created hash-verified backup')")
    archives = service.backups()
    assert len(archives) == 1 and archives[0]["schema"] == "kinelab.backup.v2"
    browser("snapshot", "-i")
    browser("find", "label", "Restore From Archive (in projects/backups/)", "fill", archives[0]["filename"])
    before = service.index.verify_audit()
    browser("find", "role", "button", "click", "--name", "Restore", "--exact")
    wait_for("document.body.textContent.includes('Verified complete recovery in recovery-generations/')")
    from recording_store import RecordingStore
    from session_index import SessionIndex
    generations = list((service.projects_root / "recovery-generations").iterdir())
    assert len(generations) == 1
    restored_index = SessionIndex(generations[0] / ".kinelab_index.db", generations[0], read_only=True)
    try:
        assert restored_index.verify_audit() == before == service.index.verify_audit()
        restored = RecordingStore(restored_index)
        assert restored.verify(sid)["manifest_sha256"] == final["manifest_sha256"]
        assert restored.verify(draft["session_id"])["manifest_sha256"] == recovered["manifest_sha256"]
        assert len(restored.list_recordings()) == len(service.recordings.list_recordings()) == 2
    finally:
        restored_index.close()
    checks["backup_and_isolated_recovery_preserve_recordings_and_audit"] = True
    browser("screenshot", str(output / "verified-recovery-generation.png"))
    assert not browser("errors").get("errors", [])
    return checks
