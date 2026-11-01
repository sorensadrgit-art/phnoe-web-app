"""Prepared only: mounted TEST_ONLY R08 export checks; never a runtime receipt."""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from unittest.mock import patch

LOGGER = logging.getLogger(__name__)

SID = "TEST_ONLY-report-current-context"
PANEL = 'section[aria-label="Evidence export"]'
PROBE_ATTRIBUTE = "_r08_generated_codec_probe"


def prepare_fixture(service):
    # Reuse the registered-real fixture contract that the actual public API tests use.
    # These are generated non-codec bytes; the codec observation is explicitly doubled.
    from native_evidence_fixture import complete_native_fixture
    from run_pipeline import validate_run_evidence
    from session_contract import ROLES, load_session, sha256_file
    from session_metadata_revision import read_metadata_state
    from setup_project import register_captures
    from test_report_current_context import initial_metadata

    folder = service.projects_root / SID
    (folder / "raw").mkdir(parents=True, exist_ok=False)
    (folder / "Config.toml").write_text("# TEST_ONLY generated\n[project]\n", encoding="utf-8")
    for role in ROLES:
        (folder / "raw" / f"{role}.mp4").write_bytes(("TEST_ONLY non-codec " + role).encode())
    metadata = initial_metadata()
    (folder / "session-template.json").write_text(json.dumps({
        "schema": "kinelab.session-template.v1", "session_id": SID,
        "kind": "real", "metadata": metadata,
    }) + "\n", encoding="utf-8")
    register_captures(folder, SID, metadata=metadata)
    assert load_session(folder)["session_id"] == SID
    complete_native_fixture(folder, "", through="poseEstimation")
    validate_run_evidence(folder, through="poseEstimation")
    probe = patch("session_index.probe_clip", return_value={
        "width": 1024, "height": 576, "fps": 30, "duration": 8})
    # Register the cleanup before starting the explicitly generated-only probe.
    setattr(service, PROBE_ATTRIBUTE, probe)
    probe.start()
    service.index.reindex()
    state = read_metadata_state(service.index, SID)
    assert state["status"] == "AVAILABLE", state
    assert state["metadata"] == metadata
    assert state["origin"]["sha256"] == sha256_file(folder / "session.json")
    passport = service.index.get_passport(SID)
    assert passport["state"] not in ("EVIDENCE_INVALID", "EVIDENCE_UNVERIFIED"), passport
    service.generate_reports(SID, confirm=True)
    originals = {str(path.relative_to(folder)): sha256_file(path)
                 for path in (folder / "raw").iterdir()}
    originals["session.json"] = sha256_file(folder / "session.json")
    service._r08_originals = originals
    return {"session_id": SID, "test_only": True, "contract_kind": "real",
            "input": "generated non-codec bytes", "codec_observation": "explicit test double",
            "native_model_execution": False, "human_annotation": False,
            "clinical_validation": "UNVERIFIED", "original_sha256": originals}


def cleanup_fixture(service):
    probe = getattr(service, PROBE_ATTRIBUTE, None)
    if probe is not None:
        probe.stop()
        delattr(service, PROBE_ATTRIBUTE)


TRANSPORT = r"""
(() => {
  if (window.__r08) throw Error('R08 transport already installed');
  const original = window.fetch;
  const state = window.__r08 = {
    mode: 'normal', posts: [], requests: [], statuses: [], held: false,
    release: null, cancelled: 0, faults: [], original, downloads: 0
  };
  const create = URL.createObjectURL.bind(URL);
  state.restoreURL = URL.createObjectURL;
  URL.createObjectURL = function(blob) { state.downloads++; return create(blob); };
  window.fetch = async function(input, options={}) {
    const url = typeof input === 'string' ? input : input.url;
    const pathname = new URL(url, location.href).pathname;
    const listRead = state.watchMetadataList && pathname === '/api/v1/sessions';
    const pollFailure = state.pollFailure && pathname.endsWith('/passport');
    const relevant = listRead || pollFailure || pathname.includes('/evidence-exports') || pathname.endsWith('/report-context');
    if (!relevant) return original.call(this, input, options);
    const method = options.method || (typeof input === 'object' && input.method) || 'GET';
    const headers = new Headers(options.headers || (typeof input === 'object' && input.headers) || {});
    state.requests.push({pathname, method, authenticated: headers.has('Authorization')});
    const context = pathname.endsWith('/report-context');
    const post = method === 'POST' && pathname.endsWith('/evidence-exports');
    const artifact = pathname.endsWith('/artifact');
    if (post) state.posts.push(JSON.parse(options.body));
    if (state.mode === 'auth401' && context) headers.delete('Authorization');
    const response = await original.call(this, input, {...options, headers});
    state.statuses.push({pathname, status: response.status});
    if (listRead) {
      const value = await response.clone().json();
      state.metadataResponseMatched = value.sessions?.some(row=>row.id===state.expectedMetadataSid&&row.metadata_context_sha256===state.expectedMetadataContext);
      const json = response.json.bind(response);
      response.json = async () => {
        const result=await json(); state.metadataListObserved=state.metadataResponseMatched; return result;
      };
      return response;
    }
    if (pollFailure) {
      await response.arrayBuffer(); state.pollFailureObserved=true;
      return new Response('{"error":"TEST_ONLY isolated polling failure"}',{status:503,headers:{'Content-Type':'application/json'}});
    }
    if (state.mode==='oversize-error' && context) {
      await response.arrayBuffer();
      return new Response('{"error":"'+'x'.repeat(8193)+'"}',{status:403,headers:{'Content-Type':'application/json'}});
    }
    if (state.mode==='oversize-archive-receipt' && post) {
      const receipt=await response.json();receipt.archive.bytes=192*1024*1024+1;
      return new Response(JSON.stringify(receipt),{status:200,headers:{'Content-Type':'application/json'}});
    }
    if (state.mode === 'lost-response' && post) {
      state.mode = 'normal';
      await response.arrayBuffer();
      throw new TypeError('TEST_ONLY response lost after actual publication');
    }
    if (state.mode === 'malformed-context' && context || state.mode === 'malformed-receipt' && post) {
      await response.arrayBuffer();
      return new Response('{"schema":', {status:200, headers:{'Content-Type':'application/json'}});
    }
    if (state.mode === 'oversize-context' && context ||
        state.mode === 'oversize-receipt' && post) {
      await response.arrayBuffer();
      return new Response(' '.repeat(65537), {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (state.mode === 'nonfinite-context' && context) {
      const raw = await response.text();
      // A syntactically numeric JSON value that JSON.parse maps to Infinity.
      return new Response(raw.replace(/"schema"\s*:/, '"TEST_ONLY_nonfinite":1e999,"schema":'),
        {status:200,headers:{'Content-Type':'application/json'}});
    }
    if (state.mode === 'held-artifact' && artifact) {
      state.held = true;
      state.heldSignal = options.signal;
      await new Promise(resolve => { state.release = resolve; });
      const cancel=response.body.cancel.bind(response.body);
      response.body.cancel=async (...args)=>{try{return await cancel(...args);}finally{state.staleSettled=true;}};
      return response;
    }
    if (artifact && ['archive-limit','archive-limit-plus-one'].includes(state.mode)) {
      await response.arrayBuffer();
      const h=new Headers(response.headers);
      h.set('Content-Length',String(192*1024*1024+(state.mode==='archive-limit-plus-one'?1:0)));
      // Refusal-only inconsistent header versus genuine small receipt; no 192 MiB allocation.
      return new Response(new ReadableStream({
        pull(controller){state.boundaryReads=(state.boundaryReads||0)+1;controller.close();},
        cancel(){state.boundaryCancelled=(state.boundaryCancelled||0)+1;}
      },{highWaterMark:0}),{status:200,headers:h});
    }
    if (artifact && ['digest-mismatch','stream-failure','cancel-failure'].includes(state.mode)) {
      const bytes = new Uint8Array(await response.arrayBuffer());
      const h = new Headers(response.headers);
      if (state.mode === 'digest-mismatch') {
        bytes[0] ^= 1;
        return new Response(bytes, {status:response.status,headers:h});
      }
      if (state.mode === 'stream-failure') return new Response(new ReadableStream({
        pull(controller) { controller.error(new Error('TEST_ONLY ZIP stream failure')); },
        cancel() { state.cancelled++; }
      }), {status:response.status,headers:h});
      h.set('Content-Length', String(bytes.length + 1));
      return new Response(new ReadableStream({
        start(controller) { controller.enqueue(bytes); },
        cancel() { state.cancelled++; throw Error('TEST_ONLY secondary cancellation failure'); }
      }), {status:response.status,headers:h});
    }
    return response;
  };
  state.restoreDigestDescriptor=Object.getOwnPropertyDescriptor(crypto.subtle,'digest');
  state.originalDigest=crypto.subtle.digest.bind(crypto.subtle);
  Object.defineProperty(crypto.subtle,'digest',{configurable:true,value:async (...args)=>{
    if(state.mode==='digest-stall'){
      state.digestHeld=true;await new Promise(resolve=>{state.releaseDigest=resolve;});
      try{return await state.originalDigest(...args);}finally{state.digestSettled=true;}
    }
    return state.originalDigest(...args);
  }});
  return true;
})()
"""


def run_checks(browser, evaluate, wait_for, service, output, checks, reopen):
    del reopen  # Preserve the established callback signature.
    from session_contract import sha256_file

    selector = '[aria-label="Select active session"]'
    wait_for("[...document.querySelectorAll(" + json.dumps(selector + " option") +
             ")].some(option=>option.value===" + json.dumps(SID) + ")")
    browser("select", selector, SID)
    wait_for("document.querySelector(" + json.dumps(selector) + ").value===" + json.dumps(SID))
    browser("scrollintoview", ".uw-nav-link:has-text('Reports')")
    browser("find", "role", "button", "click", "--name", "Reports Local evidence and exports")
    wait_for("document.querySelector(" + json.dumps(PANEL + " fieldset") + ")?.disabled===false")
    assert evaluate(TRANSPORT) is True
    original_downloads = service.projects_root.parent / "downloads"

    def record(name, **evidence):
        entry = {"id": name, "status": "PASS", "evidence": evidence}
        if name in checks:
            raise AssertionError("Duplicate browser case identifier")
        checks[name] = entry
        # Durable per-case evidence survives a later browser or collector failure.
        (output / f"{name}.json").write_text(json.dumps(entry, indent=2) + "\n", encoding="utf-8")

    def reset(mode="normal"):
        evaluate("window.__r08.mode='normal';if(window.__r08.release)window.__r08.release()")
        browser("select", selector, "synthetic-race-b")
        wait_for("document.querySelector(" + json.dumps(selector) + ").value==='synthetic-race-b'")
        browser("select", selector, SID)
        wait_for("document.querySelector(" + json.dumps(PANEL + " fieldset") + ")?.disabled===false")
        evaluate("window.__r08.mode=" + json.dumps(mode) +
                 ";window.__r08.posts=[];window.__r08.requests=[];window.__r08.statuses=[];" +
                 "window.__r08.held=false;window.__r08.release=null;"
                 "window.__r08.staleSettled=false;window.__r08.pollFailure=false;"
                 "window.__r08.pollFailureObserved=false;window.__r08.boundaryReads=0;"
                 "window.__r08.boundaryCancelled=0;window.__r08.digestHeld=false;"
                 "window.__r08.digestSettled=false;window.__r08.releaseDigest=null")
        browser("check", PANEL + ' input[name="evidence-profile"][value="privacy-reduced"]')
        browser("check", PANEL + ' [aria-label="Confirm evidence export"]')

    def click(label):
        browser("find", "role", "button", "click", "--name", label)

    def publish():
        click("Create evidence export")

    def ready():
        wait_for("[...document.querySelectorAll(" + json.dumps(PANEL + " button") +
                 ")].some(b=>b.textContent==='Download verified export'&&!b.disabled)")

    def refusal(*, no_receipt=True):
        wait_for("Boolean(document.querySelector(" + json.dumps(PANEL + " [role=alert]") + ")?.textContent)")
        text = evaluate("document.querySelector(" + json.dumps(PANEL + " [role=alert]") + ").textContent")
        assert text, "A useful mounted refusal is required"
        if no_receipt:
            assert not evaluate("[...document.querySelectorAll(" + json.dumps(PANEL + " button") +
                                ")].some(b=>b.textContent==='Download verified export')")
        return text

    def saved_zip(name):
        posts = evaluate("window.__r08.posts")
        operation = posts[-1]["operation_id"]
        receipt = service.evidence_export_receipt(SID, operation)
        expected = service.evidence_export_artifact(SID, operation)
        assert expected.startswith(b"PK"), "Actual audited publisher must supply the archive"
        destination = output / (name + ".zip")
        assert not destination.exists()
        click("Download verified export")
        browser("wait", "--download", str(destination))
        actual = destination.read_bytes()
        assert actual == expected, "Saved browser download differs from actual verified artifact bytes"
        digest = hashlib.sha256(actual).hexdigest()
        assert digest == receipt["archive"]["sha256"], receipt
        return {"operation_id": operation, "bytes": len(actual), "sha256": digest,
                "saved_file": destination.name}

    def no_new_zip(before, activated):
        after = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
        assert after == before, "A refused/stale operation saved a browser download"
        assert evaluate("window.__r08.downloads") == activated, "A refused operation activated a Blob URL"

    try:
        reset()
        publish()
        ready()
        success = saved_zip("R08_BROWSER_00_success")
        requests = evaluate("window.__r08.requests")
        assert requests and all(r["authenticated"] for r in requests)
        record("R08_BROWSER_00_success", **success, authenticated_requests=True)

        reset("lost-response")
        publish()
        error = refusal()
        assert "unconfirmed" in error.lower(), error
        original = evaluate("window.__r08.posts[0]")
        click("Retry exact export")
        ready()
        posts = evaluate("window.__r08.posts")
        assert len(posts) == 2 and posts[0] == posts[1] == original
        retry = saved_zip("R08_BROWSER_01_exact_retry")
        record("R08_BROWSER_01_exact_retry", **retry, same_body=True)

        reset("auth401")
        publish()
        error = refusal()
        observations = evaluate("window.__r08.statuses")
        assert any(row["status"] == 401 for row in observations), observations
        assert evaluate("window.__r08.posts.length") == 0
        record("R08_BROWSER_02_actual_auth401", refusal=error, actual_server_status=401)

        for mode in ("malformed-context", "malformed-receipt", "oversize-context", "oversize-receipt"):
            reset(mode)
            before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
            activated = evaluate("window.__r08.downloads")
            publish()
            error = refusal()
            no_new_zip(before, activated)
            if mode.endswith("context"):
                assert evaluate("window.__r08.posts.length") == 0, "Invalid context must not publish"
            record("R08_BROWSER_03_" + mode.replace("-", "_"), refusal=error,
                   boundary="actual mounted caller with injected HTTP response")

        for mode in ("digest-mismatch", "stream-failure", "cancel-failure"):
            reset()
            publish()
            ready()
            before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
            activated = evaluate("window.__r08.downloads")
            evaluate("window.__r08.mode=" + json.dumps(mode))
            click("Download verified export")
            error = refusal(no_receipt=False)
            no_new_zip(before, activated)
            if mode == "cancel-failure":
                assert "secondary cancellation failure" not in error, error
                assert evaluate("window.__r08.cancelled") > 0
            record("R08_BROWSER_04_" + mode.replace("-", "_"), refusal=error)

        reset()
        publish()
        ready()
        before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
        activated = evaluate("window.__r08.downloads")
        evaluate("window.__r08.mode='held-artifact'")
        click("Download verified export")
        wait_for("window.__r08.held")
        # Real DOM select events exercise the mounted App handler; no callback hook.
        evaluate("(()=>{const s=document.querySelector(" + json.dumps(selector) +
                 ");s.value='synthetic-race-b';s.dispatchEvent(new Event('change',{bubbles:true}));" +
                 "s.value=" + json.dumps(SID) + ";s.dispatchEvent(new Event('change',{bubbles:true}));" +
                 "if(!window.__r08.heldSignal?.aborted)throw Error('Mounted App did not abort obsolete operation');" +
                 "window.__r08.release();return true})()")
        wait_for("!document.querySelector(" + json.dumps(PANEL + " fieldset") + ")?.disabled")
        no_new_zip(before, activated)
        wait_for("window.__r08.staleSettled===true")
        no_new_zip(before, activated)
        record("R08_BROWSER_05_batched_A_B_A", no_stale_download=True, old_response_cancel_settled=True)


        reset("oversize-error")
        before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
        activated = evaluate("window.__r08.downloads")
        publish()
        error = refusal()
        assert len(error.encode("utf-8")) < 8192, "Oversize API error text leaked into UI"
        assert evaluate("window.__r08.posts.length") == 0
        no_new_zip(before, activated)
        record("R08_BROWSER_07_error_8KiB_refusal", refusal=error,
               isolated_transport=True, injected_body_bytes_greater_than=8192)

        reset("oversize-archive-receipt")
        before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
        activated = evaluate("window.__r08.downloads")
        publish()
        error = refusal()
        no_new_zip(before, activated)
        record("R08_BROWSER_08_receipt_over_192MiB", refusal=error,
               isolated_receipt_size=True, allocated_192MiB=False)

        for mode in ("archive-limit", "archive-limit-plus-one"):
            reset()
            publish()
            ready()
            before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
            activated = evaluate("window.__r08.downloads")
            evaluate("window.__r08.mode=" + json.dumps(mode))
            click("Download verified export")
            error = refusal(no_receipt=False)
            assert evaluate("window.__r08.boundaryReads") == 0, "Boundary refusal consumed body"
            assert evaluate("window.__r08.boundaryCancelled") == 1, "Refused body not cancelled"
            no_new_zip(before, activated)
            record("R08_BROWSER_08_" + mode.replace("-", "_"), refusal=error,
                   isolated_header_and_stream=True, allocated_192MiB=False,
                   genuine_small_receipt=True, genuine_192MiB_acceptance="NOT_RUN")

        reset()
        publish()
        ready()
        before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
        activated = evaluate("window.__r08.downloads")
        evaluate("window.__r08.mode='digest-stall'")
        click("Download verified export")
        wait_for("window.__r08.digestHeld===true")
        evaluate("(()=>{const s=document.querySelector(" + json.dumps(selector) +
                 ");s.value='synthetic-race-b';s.dispatchEvent(new Event('change',{bubbles:true}));" +
                 "s.value=" + json.dumps(SID) + ";s.dispatchEvent(new Event('change',{bubbles:true}));" +
                 "window.__r08.releaseDigest();return true})()")
        wait_for("window.__r08.digestSettled===true")
        evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))")
        no_new_zip(before, activated)
        record("R08_BROWSER_09_digest_stall_A_B_A", isolated_crypto_stall=True,
               actual_server_archive=True, digest_continuation_settled=True)

        # Last authority-changing case uses actual publisher, same SID, identical effective values.
        reset()
        publish()
        ready()
        before = sorted(p.name for p in original_downloads.iterdir()) if original_downloads.exists() else []
        activated = evaluate("window.__r08.downloads")
        evaluate("window.__r08.mode='digest-stall'")
        click("Download verified export")
        wait_for("window.__r08.digestHeld===true")
        from session_metadata_revision import read_metadata_state
        initial = read_metadata_state(service.index, SID)
        service.publish_metadata_revision(SID, {
            "metadata": initial["metadata"], "expected_origin_sha256": initial["origin"]["sha256"],
            "expected_head_sha256": initial["head"]["sha256"] if initial["head"] else None,
            "operation_id": "c" * 32, "reason_code": "operator_correction", "confirm": True,
        })
        changed = read_metadata_state(service.index, SID)
        assert changed["context_sha256"] != initial["context_sha256"]
        evaluate("window.__r08.watchMetadataList=true;window.__r08.metadataListObserved=false;"
                 "window.__r08.expectedMetadataSid=" + json.dumps(SID) + ";"
                 "window.__r08.expectedMetadataContext=" + json.dumps(changed["context_sha256"]) + ";"
                 "window.__r08.pollFailure=true")
        wait_for("window.__r08.pollFailureObserved===true")
        evaluate("window.__r08.pollFailure=false")
        wait_for("[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Retry Connection'&&!b.disabled)")
        browser("find", "role", "button", "click", "--name", "Retry Connection")
        wait_for("window.__r08.metadataListObserved===true")
        assert evaluate("document.querySelector(" + json.dumps(selector) + ").value") == SID
        evaluate("window.__r08.releaseDigest()")
        wait_for("window.__r08.digestSettled===true")
        evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))")
        no_new_zip(before, activated)
        record("R08_BROWSER_10_same_session_metadata_revision", same_sid=True,
               actual_metadata_publication=True, actual_list_refresh_consumed=True,
               metadata_context_changed=True, isolated_poll_failure_to_reveal_retry=True,
               isolated_crypto_stall=True)

        for relative, expected in service._r08_originals.items():
            assert sha256_file(service.projects_root / SID / relative) == expected, relative
        assert evaluate("window.__cameraRequests") == 0
        record("R08_BROWSER_06_original_inputs_unchanged", actual_camera_calls=0)
        browser("screenshot", str(output / "evidence-export-mounted.png"))
    except Exception as primary_error:
        # Capture only bounded generated-panel/transport diagnostics before teardown.
        try:
            diagnostics = evaluate(r"""(() => {
              const panel = document.querySelector('section[aria-label="Evidence export"]');
              const transport = window.__r08;
              const clip = (value, limit) => String(value ?? '').slice(0, limit);
              const controls = panel ? [...panel.querySelectorAll('input')] : [];
              const requests = Array.isArray(transport?.requests) ? transport.requests : [];
              const statuses = Array.isArray(transport?.statuses) ? transport.statuses : [];
              return {
                panel_present: Boolean(panel),
                panel_text: clip(panel?.textContent, 2048),
                alerts: panel ? [...panel.querySelectorAll('[role="alert"]')].slice(0, 8)
                  .map(node => clip(node.textContent, 512)) : [],
                buttons: panel ? [...panel.querySelectorAll('button')].slice(0, 16)
                  .map(node => ({label: clip(node.textContent, 128), disabled: node.disabled === true})) : [],
                selected_session_id: clip(document.querySelector('[aria-label="Select active session"]')?.value, 128),
                fieldset_disabled: panel?.querySelector('fieldset')?.disabled ?? null,
                profiles: controls.filter(node => node.name === 'evidence-profile').slice(0, 2)
                  .map(node => ({value: clip(node.value, 32), checked: node.checked === true})),
                confirm_export: controls.find(node => node.getAttribute('aria-label') === 'Confirm evidence export')?.checked === true,
                confirm_full: controls.find(node => node.getAttribute('aria-label') === 'Confirm full disclosure')?.checked === true,
                transport_present: Boolean(transport),
                transport_mode: clip(transport?.mode, 32),
                posts_count: Array.isArray(transport?.posts) ? transport.posts.length : 0,
                request_count: requests.length,
                status_count: statuses.length,
                requests: requests.slice(-64).map(item => ({
                  pathname: clip(item?.pathname, 256), method: clip(item?.method, 12),
                  authenticated: item?.authenticated === true,
                })),
                statuses: statuses.slice(-64).map(item => ({
                  pathname: clip(item?.pathname, 256),
                  status: Number.isInteger(item?.status) && item.status >= 100 && item.status <= 599 ? item.status : null,
                })),
              };
            })()""")
            with (output / "scenario-diagnostics.json").open("x", encoding="utf-8") as stream:
                json.dump({
                    "schema": "kinelab.r08-browser-diagnostics.v1", "status": "DIAGNOSTIC_ONLY",
                    "primary_type": type(primary_error).__name__, "snapshot": diagnostics,
                }, stream, sort_keys=True)
                stream.write("\n")
        except Exception as diagnostics_error:
            LOGGER.exception("Scenario diagnostics failed: %s", type(diagnostics_error).__name__, exc_info=False)
            primary_error.add_note("Scenario diagnostics failed: " + type(diagnostics_error).__name__)
            try:
                with (output / "scenario-diagnostics-failure.json").open("x", encoding="utf-8") as stream:
                    json.dump({
                        "status": "FAIL", "type": type(diagnostics_error).__name__,
                        "primary_preserved": True,
                    }, stream, sort_keys=True)
                    stream.write("\n")
            except Exception as evidence_error:
                LOGGER.exception("Scenario diagnostics evidence write failed: %s", type(evidence_error).__name__, exc_info=False)
                primary_error.add_note("Scenario diagnostics evidence write failed: " + type(evidence_error).__name__)
                raise primary_error from None
            raise primary_error from None
        raise
    finally:
        primary = sys.exc_info()[1]
        try:
            evaluate("(()=>{const s=window.__r08;if(!s)return;if(s.release)s.release();" +
                     "if(s.releaseDigest)s.releaseDigest();"
                     "if(s.restoreDigestDescriptor)Object.defineProperty(crypto.subtle,'digest',s.restoreDigestDescriptor);"
                     "else delete crypto.subtle.digest;"
                     "window.fetch=s.original;URL.createObjectURL=s.restoreURL;delete window.__r08})()")
        except Exception as cleanup_error:
            if primary is not None:
                primary.add_note("Transport cleanup failed: " + type(cleanup_error).__name__)
            try:
                (output / "transport-cleanup-failure.json").write_text(json.dumps({
                    "status": "FAIL", "type": type(cleanup_error).__name__,
                    "primary_preserved": primary is not None,
                }) + "\n", encoding="utf-8")
            except Exception as evidence_error:
                LOGGER.exception("Transport cleanup evidence write failed: %s", type(evidence_error).__name__, exc_info=False)
                preserved = primary if primary is not None else cleanup_error
                preserved.add_note("Transport cleanup evidence write failed: " + type(evidence_error).__name__)
                raise preserved from None
            if primary is None:
                raise

