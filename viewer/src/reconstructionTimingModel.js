const record = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys) => record(value) && Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const integer = value => Number.isSafeInteger(value) && value >= 0;
const finite = value => typeof value === 'number' && Number.isFinite(value) && value >= 0;
const hash = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const near = (a, b) => finite(a) && finite(b) && Math.abs(a - b) <= 1e-6;
const schema = 'kinelab.reconstruction-timing.v1';
const policy = 'adjacent_observed_endpoints_v1; [start,end) partition; rejected includes transitions; no endpoint extrapolation';
const categories = ['valid_adjacent', 'rejected_or_transition_adjacent', 'unknown_gap'];
const flags = value => value.physical_accuracy_verified === false && value.clinical_accuracy_verified === false && value.clinical_validation === 'UNVERIFIED';
const identity = value => exact(value, ['path', 'sha256']) && typeof value.path === 'string' &&
  value.path.length > 0 && value.path.length <= 512 && !value.path.includes('\\') &&
  !value.path.startsWith('/') && !value.path.includes(':') &&
  value.path.split('/').every(part => part && part !== '.' && part !== '..') && hash(value.sha256);
const sameIdentity = (left, right) => identity(left) && identity(right) && left.path === right.path && left.sha256 === right.sha256;

export const TIMING_LABELS = Object.freeze({
  valid_adjacent: 'valid adjacent endpoints',
  rejected_or_transition_adjacent: 'rejected/transition adjacent',
  unknown_gap: 'unknown gap',
});
export const timingUnavailable = code => ({
  status: 'UNAVAILABLE', code, reason: code, segments: [], gaps: [], intervals: [], duration_s: null,
});

export function parseReconstructionTiming(value, expected) {
  if (value === undefined) return timingUnavailable('TIMING_NOT_REPORTED');
  const invalid = () => timingUnavailable('TIMING_INVALID');
  if (!record(value) || value.schema !== schema || !flags(value)) return invalid();
  if (value.status === 'UNAVAILABLE') {
    if (!exact(value, ['schema', 'status', 'code', 'reason', 'duration_s', 'segments', 'gaps', 'intervals',
      'physical_accuracy_verified', 'clinical_accuracy_verified', 'clinical_validation']) ||
      typeof value.code !== 'string' || !/^TIMING_[A-Z_]{1,64}$/.test(value.code) ||
      value.reason !== value.code || value.duration_s !== null ||
      !['segments', 'gaps', 'intervals'].every(key => Array.isArray(value[key]) && value[key].length === 0)) return invalid();
    return timingUnavailable(value.code);
  }
  if (value.status !== 'AVAILABLE' || !exact(value, ['schema', 'status', 'session_id', 'source_trc', 'calibration',
    'sample_counts', 'segments', 'gaps', 'intervals', 'duration_s', 'duration_policy', 'source_extent',
    'physical_accuracy_verified', 'clinical_accuracy_verified', 'clinical_validation', 'bindings']) ||
    !record(expected) || value.duration_policy !== policy ||
    value.source_extent !== 'leading/trailing and decoded source video extent UNVERIFIED') return invalid();
  const b = value.bindings;
  if (!exact(b, ['session_id', 'session_sha256', 'run_sha256', 'source_trc', 'calibration', 'frame_diagnostics',
    'metadata_context_sha256', 'comparison_source_observation']) ||
    value.session_id !== expected.session_id || b.session_id !== expected.session_id ||
    !['session_sha256', 'run_sha256', 'metadata_context_sha256'].every(key => hash(b[key]) && b[key] === expected[key]) ||
    !sameIdentity(value.source_trc, b.source_trc) || !sameIdentity(value.calibration, b.calibration) ||
    !identity(b.frame_diagnostics) || value.calibration.sha256 !== expected.calibration_sha256 ||
    !exact(b.comparison_source_observation, ['token', 'evidence_verified']) ||
    b.comparison_source_observation.evidence_verified !== false || !hash(b.comparison_source_observation.token) ||
    b.comparison_source_observation.token !== expected.token) return invalid();
  const counts = value.sample_counts;
  if (!exact(counts, ['observed', 'valid', 'rejected', 'missing_interior']) ||
    !Object.values(counts).every(integer) || counts.observed < 1 || counts.observed > 4096 ||
    counts.valid + counts.rejected !== counts.observed ||
    !['segments', 'gaps', 'intervals'].every(key => Array.isArray(value[key]) && value[key].length <= 4096)) return invalid();
  const rows = [];
  const boundaryTimes = new Map();
  let valid = 0, rejected = 0, previous = null;
  for (const segment of value.segments) {
    if (!exact(segment, ['classification', 'first_frame', 'last_frame', 'first_time_s', 'last_time_s', 'samples']) ||
      !['valid', 'rejected'].includes(segment.classification) ||
      ![segment.first_frame, segment.last_frame, segment.samples].every(integer) ||
      segment.samples < 1 || segment.samples > 4096 ||
      segment.last_frame - segment.first_frame + 1 !== segment.samples ||
      rows.length + segment.samples > counts.observed ||
      !near(segment.first_time_s, segment.first_frame / 30) || !near(segment.last_time_s, segment.last_frame / 30) ||
      (previous && (segment.first_frame <= previous.last_frame ||
        (segment.first_frame === previous.last_frame + 1 && segment.classification === previous.classification)))) return invalid();
    for (let offset = 0; offset < segment.samples; offset++) rows.push({frame: segment.first_frame + offset, rejected: segment.classification === 'rejected'});
    if (segment.classification === 'valid') valid += segment.samples; else rejected += segment.samples;
    if (segment.samples === 1 && segment.first_time_s !== segment.last_time_s) return invalid();
    boundaryTimes.set(segment.first_frame, segment.first_time_s);
    boundaryTimes.set(segment.last_frame, segment.last_time_s);
    previous = segment;
  }
  if (rows.length !== counts.observed || valid !== counts.valid || rejected !== counts.rejected ||
    value.intervals.length !== rows.length - 1) return invalid();
  const missing = rows.at(-1).frame - rows[0].frame + 1 - rows.length;
  if (!integer(missing) || missing !== counts.missing_interior) return invalid();
  const sums = Object.fromEntries(categories.map(key => [key, 0]));
  let gapIndex = 0, priorEnd = null;
  for (let index = 0; index < value.intervals.length; index++) {
    const interval = value.intervals[index], left = rows[index], right = rows[index + 1];
    const gap = right.frame > left.frame + 1;
    const category = gap ? 'unknown_gap' : left.rejected || right.rejected ? 'rejected_or_transition_adjacent' : 'valid_adjacent';
    if (!exact(interval, ['left_frame', 'right_frame', 'start_time_s', 'end_time_s', 'category']) ||
      interval.left_frame !== left.frame || interval.right_frame !== right.frame || interval.category !== category ||
      !near(interval.start_time_s, left.frame / 30) || !near(interval.end_time_s, right.frame / 30) ||
      interval.end_time_s <= interval.start_time_s || (priorEnd !== null && interval.start_time_s !== priorEnd)) return invalid();
    if ((boundaryTimes.has(left.frame) && interval.start_time_s !== boundaryTimes.get(left.frame)) ||
        (boundaryTimes.has(right.frame) && interval.end_time_s !== boundaryTimes.get(right.frame))) return invalid();
    priorEnd = interval.end_time_s;
    sums[category] += interval.end_time_s - interval.start_time_s;
    if (gap) {
      const item = value.gaps[gapIndex++];
      if (!exact(item, ['first_missing_frame', 'last_missing_frame', 'missing_samples', 'left_time_s', 'right_time_s']) ||
        item.first_missing_frame !== left.frame + 1 || item.last_missing_frame !== right.frame - 1 ||
        item.missing_samples !== right.frame - left.frame - 1 ||
        item.left_time_s !== interval.start_time_s || item.right_time_s !== interval.end_time_s) return invalid();
    }
  }
  if (gapIndex !== value.gaps.length || !exact(value.duration_s, [...categories, 'observed_span']) ||
    !Object.values(value.duration_s).every(finite) ||
    !categories.every(key => near(value.duration_s[key], sums[key])) ||
    !near(value.duration_s.observed_span, categories.reduce((sum, key) => sum + sums[key], 0)) ||
    !near(value.duration_s.observed_span, (rows.at(-1).frame - rows[0].frame) / 30)) return invalid();
  return value;
}

export function parseComparisonTimings(raw, ids, sessionRows) {
  const payload = record(raw) && Object.hasOwn(raw, 'comparison') ? raw.comparison : raw;
  const sources = payload?.research_measurements?.sessions;
  return Object.fromEntries(ids.map(id => {
    const matches = Array.isArray(sources) ? sources.filter(source => source?.session_id === id) : [];
    const rows = sessionRows.filter(row => row?.id === id);
    if (matches.length !== 1 || rows.length !== 1) return [id, timingUnavailable('TIMING_SOURCE_UNAVAILABLE')];
    const source = matches[0], row = rows[0], revision = source.source_revision;
    return [id, parseReconstructionTiming(source.timing, {
      session_id: id, session_sha256: revision?.session_sha256, run_sha256: revision?.run_sha256,
      calibration_sha256: revision?.calibration_sha256, metadata_context_sha256: row.metadata_context_sha256,
      token: row.research_source_revision?.status === 'AVAILABLE' ? row.research_source_revision.token : undefined,
    })];
  }));
}
