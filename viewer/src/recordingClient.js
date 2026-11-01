// Bounded synthetic transport. A server acknowledgment is the only saved-frame signal.
export const RECORDING_LIMITS = Object.freeze({chunkFrames:16, pendingFrames:64, frames:54000, durationMs:1800000});
const reasons = new Set(['NO_POSE','LOW_CONFIDENCE','OCCLUDED','STALE','DEVICE_LOST','GAP','MODEL_UNAVAILABLE',
  'INVALID_GEOMETRY','MULTIPLE_PEOPLE','PAUSED','BACKPRESSURE','INFERENCE_ERROR']);
const requiredJoints = [11,12,23,24,25,26,27,28];
const limbs = [[11,23],[12,24],[23,25],[24,26],[25,27],[26,28]];
const fail = reason => { throw new Error(`MEASUREMENT_INVALID: ${reason}`); };
const id = () => crypto.randomUUID().replaceAll('-','');

export async function sha256Text(value) {
  const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(value));
  return Array.from(new Uint8Array(bytes), n=>n.toString(16).padStart(2,'0')).join('');
}

export function validateObservation(value) {
  if (!value || Object.keys(value).sort().join(',') !== 'landmarks,reasons,time_ms,valid') fail('observation fields');
  if (!Number.isFinite(value.time_ms) || value.time_ms < 0 || value.time_ms > RECORDING_LIMITS.durationMs) fail('time_ms');
  if (typeof value.valid !== 'boolean' || !Array.isArray(value.reasons) ||
      value.reasons.some(r=>!reasons.has(r)) || new Set(value.reasons).size !== value.reasons.length ||
      Boolean(value.reasons.length) === value.valid) fail('validity reasons');
  const points = value.landmarks;
  if (points === null) { if (value.valid) fail('missing pose'); return value; }
  if (!Array.isArray(points) || points.length !== 33) fail('33 landmarks required');
  points.forEach(point=>{
    if (point === null) return;
    if (!Array.isArray(point) || point.length !== 4 || point.some((n,i)=>
      !Number.isFinite(n) || (i !== 2 && (n < 0 || n > 1)))) fail('landmark coordinates/confidence');
  });
  if (value.valid && (requiredJoints.some(j=>!points[j] || points[j][3]<.5) ||
      limbs.some(([a,b])=>points[a][0]===points[b][0] && points[a][1]===points[b][1]))) fail('required geometry/confidence');
  return value;
}

export class RecordingClient {
  constructor({header, request, onChange=()=>{}}) {
    if (header?.source?.kind !== 'synthetic' || !header.session_id?.startsWith('synthetic-')) fail('synthetic source required');
    this.header = structuredClone(header);
    this.request = request; this.onChange = onChange;
    this.queue = []; this.pending = null; this.draining = null;
    this.created = false; this.accepting = false; this.closed = false; this.failed = false;
    this.saved = 0; this.produced = 0; this.lastTime = -1; this.revision = 0;
    this.headerSha = null; this.message = ''; this.finalized = false; this.interrupted = false;
    this.stopped = false; this.starting = null; this.stopping = null; this.finishing = null;
    this.endpoint = `/recordings/${encodeURIComponent(header.session_id)}`;
  }
  snapshot() {
    return {sessionId:this.header.session_id, savedThrough:this.saved, producedThrough:this.produced,
      pendingFrames:this.queue.length+(this.pending?.count || 0), accepting:this.accepting,
      failed:this.failed, finalized:this.finalized, message:this.message};
  }
  notify() { if (!this.closed) this.onChange(this.snapshot()); }
  accept(receipt, expectedSaved, final=false) {
    if (receipt?.session_id !== this.header.session_id || receipt.operation_id !== this.header.operation_id ||
        receipt.source_kind !== 'synthetic' || !/^[a-f0-9]{64}$/.test(receipt.header_sha256) ||
        (this.headerSha && receipt.header_sha256 !== this.headerSha) ||
        !Number.isInteger(receipt.saved_through) || receipt.saved_through < this.saved || receipt.saved_through > this.produced ||
        !Number.isInteger(receipt.received_through) || receipt.received_through > this.produced ||
        receipt.saved_through !== expectedSaved || receipt.received_through !== expectedSaved ||
        !Number.isInteger(receipt.revision) || receipt.revision < this.revision ||
        receipt.state !== (final?'FINALIZED':'RECORDING') ||
        (final && (receipt.saved_through !== this.produced || receipt.manifest?.frame_count !== this.produced ||
          receipt.manifest?.header_sha256 !== this.headerSha || receipt.manifest?.source_kind !== 'synthetic'))) {
      throw new Error('ACK_INVALID: recording identity, sequence or generation differs');
    }
    this.headerSha = receipt.header_sha256; this.saved = receipt.saved_through; this.revision = receipt.revision;
  }
  async start() {
    if (this.created || this.closed) throw new Error('Recording already started or closed');
    this.starting = (async()=>{
      try {
        const result = await this.request('/recordings', this.header);
        if (this.closed) throw new Error('Recording closed');
        this.accept(result,0); this.created = true; this.accepting = !this.stopped; this.failed = false;
        if (!this.stopped) this.message = '';
        this.notify(); return result;
      } catch (error) { this.fail(error); throw error; }
    })();
    return this.starting;
  }
  fail(error) {
    this.failed = true; this.accepting = false; this.interrupted = true; this.message = error.message || 'Recording transport failed'; this.notify();
  }
  enqueue(observation) {
    if (!this.accepting || this.closed || this.finalized) return false;
    validateObservation(observation);
    if (observation.time_ms <= this.lastTime) fail('timestamps must increase');
    if (this.snapshot().pendingFrames >= RECORDING_LIMITS.pendingFrames || this.produced >= RECORDING_LIMITS.frames) {
      this.accepting = false; this.interrupted = true; this.message = 'BACKPRESSURE: capture stopped; retain and flush pending frames'; this.notify(); return false;
    }
    this.lastTime = observation.time_ms;
    this.queue.push({sequence:++this.produced,...structuredClone(observation)});
    if (this.queue.length >= RECORDING_LIMITS.chunkFrames) void this.flush().catch(()=>{});
    this.notify(); return true;
  }
  flush() {
    if (this.draining) return this.draining;
    if (this.failed) return Promise.reject(new Error(this.message));
    this.draining = this.drain().finally(()=>{this.draining = null;});
    return this.draining;
  }
  async drain() {
    try {
      while (!this.closed && (this.pending || this.queue.length)) {
        if (!this.pending) {
          const frames = this.queue.splice(0, RECORDING_LIMITS.chunkFrames);
          const frames_json = JSON.stringify(frames);
          this.pending = {count:frames.length, through:frames.at(-1).sequence, payload:{operation_id:this.header.operation_id,
            header_sha256:this.headerSha, chunk_id:id(), frames_json}};
        }
        const payload = this.pending.payload;
        if (!payload.sha256) payload.sha256 = await sha256Text(payload.frames_json);
        if (new TextEncoder().encode(payload.frames_json).length > 48*1024) fail('chunk exceeds 48 KiB');
        if (this.closed) break;
        const result = await this.request(`${this.endpoint}/chunks`, payload);
        if (this.closed) break;
        this.accept(result,this.pending.through); this.pending = null; this.notify();
      }
    } catch (error) { this.fail(error); throw error; }
  }
  async retry() {
    if (this.closed) throw new Error('Recording closed');
    if (!this.created) return this.start();
    this.failed = false; this.message = '';
    await this.flush(); this.notify();
  }
  stop() {
    this.stopped = true; this.accepting = false; this.interrupted = true;
    if (this.stopping) return this.stopping;
    if (this.finalized) return Promise.resolve(null);
    this.message = 'Activity stopped; recording save pending'; this.notify();
    this.stopping = (async()=>{
      if (this.starting) await this.starting;
      if (!this.created || !this.produced) {
        this.message = 'Activity stopped; no frames finalized. Retain the saved draft.'; this.notify(); return null;
      }
      return this.finish();
    })().catch(error=>{this.fail(error); throw error;});
    return this.stopping;
  }
  finish() {
    if (this.finishing) return this.finishing;
    this.finishing = this.finalize().finally(()=>{this.finishing = null;});
    return this.finishing;
  }
  async finalize() {
    if (this.closed || !this.created || !this.produced) throw new Error('No recordable frames available');
    this.accepting = false; this.notify();
    await this.flush();
    try {
      this.finalization ??= {
        operation_id:this.header.operation_id,last_sequence:this.produced,
        end_reason:this.interrupted?'capture_interrupted':'operator_finished'};
      const result = await this.request(`${this.endpoint}/finalize`, this.finalization);
      this.accept(result,this.produced,true); this.finalized = true; this.message = 'Synthetic recording finalized'; this.notify(); return result;
    } catch (error) { this.fail(error); throw error; }
  }
  close() { this.closed = true; this.accepting = false; }
}
