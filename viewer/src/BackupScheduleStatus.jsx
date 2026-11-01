import React from 'react';

const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const exact = (value, keys) => object(value) && Object.keys(value).sort().join(',') === [...keys].sort().join(',');
const integer = value => Number.isSafeInteger(value) && value >= 0 && value <= 253402300799;
const hex = (value, count) => typeof value === 'string' && new RegExp('^[a-f0-9]{' + count + '}$').test(value);
const reasons = new Set(['MEMBERS_VERIFIED', 'BUSY', 'BACKUP_FAILED', 'INTERRUPTED', 'LATE', 'CLOCK_UNCERTAIN']);
const statuses = new Set(['QUEUED', 'RUNNING', 'SUCCEEDED', 'FAILED', 'MISSED', 'INTERRUPTED']);
const invalid = () => { throw Error('Backup monitoring returned an unrecognized response.'); };

export function parseBackupScheduleStatus(value) {
  if (!object(value) || value.schema !== 'kinelab.backup-schedule-status.v1' ||
      value.enabled !== false || value.state !== 'DISABLED' || value.policy_status !== 'OPEN' ||
      value.next_due_at_utc !== null || value.last_verified_recovery_point !== null ||
      value.service_alive_only !== true || !['TEST_ONLY', 'UNCONFIGURED'].includes(value.engine_mode) ||
      !exact(value.pruning, ['enabled', 'reason']) || value.pruning.enabled !== false ||
      value.pruning.reason !== 'POLICY_NOT_APPROVED' || value.journal_capacity !== 4096 ||
      !['VALIDATED', 'RECOVERY_REQUIRED'].includes(value.journal_health) ||
      !['IDLE', 'REVIEW_REQUIRED'].includes(value.engine_health) ||
      !['NOT_ATTACHED', 'ATTACHED', 'TICK_FAILED', 'HEALTH_UNRECORDED'].includes(value.pump_status) ||
      typeof value.historical_prefix_only !== 'boolean' ||
      value.historical_prefix_only !== (value.journal_health === 'RECOVERY_REQUIRED') ||
      !Number.isSafeInteger(value.missed_count) || value.missed_count < 0 || value.missed_count > 4096 ||
      !Array.isArray(value.history) || value.history.length > 50) invalid();
  if (value.clock_health !== null && (!exact(value.clock_health, ['observed_utc', 'reference_utc']) ||
      !integer(value.clock_health.observed_utc) || !integer(value.clock_health.reference_utc) ||
      value.clock_health.observed_utc >= value.clock_health.reference_utc)) invalid();
  if (value.pump_health !== null && (!exact(value.pump_health, ['reason', 'observed_utc']) ||
      value.pump_health.reason !== 'TICK_FAILED' || !integer(value.pump_health.observed_utc))) invalid();
  const review = value.historical_prefix_only || value.clock_health !== null || value.pump_health !== null ||
    ['TICK_FAILED', 'HEALTH_UNRECORDED'].includes(value.pump_status);
  if (value.engine_health !== (review ? 'REVIEW_REQUIRED' : 'IDLE')) invalid();
  for (const job of value.history) {
    if (!object(job) || !hex(job.operation_id, 32) || job.archive !== 'scheduled-' + job.operation_id + '.zip' ||
        !statuses.has(job.status) || !integer(job.at) || !integer(job.due) ||
        (job.reason !== undefined && !reasons.has(job.reason))) invalid();
  }
  if (value.last_job !== null && (!object(value.last_job) || !value.history.length ||
      JSON.stringify(value.last_job) !== JSON.stringify(value.history.at(-1)))) invalid();
  const archive = value.last_verified_archive;
  if (archive !== null && (!exact(archive, ['archive', 'generation_id', 'sha256', 'bytes', 'verified_at', 'verification_kind']) ||
      typeof archive.archive !== 'string' || !/^scheduled-[a-f0-9]{32}\.zip$/.test(archive.archive) ||
      !hex(archive.generation_id, 32) || !hex(archive.sha256, 64) ||
      !Number.isSafeInteger(archive.bytes) || archive.bytes <= 0 || archive.bytes > 2 ** 40 ||
      !integer(archive.verified_at) || archive.verification_kind !== 'CREATED_AND_MEMBER_HASH_VERIFIED')) invalid();
  return value;
}

export default function BackupScheduleStatus({ schedule }) {
  const checked = parseBackupScheduleStatus(schedule);
  const archive = checked.last_verified_archive;
  return <>
    <p>Scheduling is disabled. Frequency, destination and retention decisions remain open. No automatic deletion is permitted.</p>
    {checked.engine_health === 'REVIEW_REQUIRED' && <p role="alert">Backup monitoring requires review. No current recovery status has been confirmed.</p>}
    {checked.journal_health === 'RECOVERY_REQUIRED' && <p role="alert">RECOVERY_REQUIRED: journal history is incomplete or invalid. Historical prefix only; no automatic repair is permitted.</p>}
    {checked.clock_health !== null && <p role="alert">CLOCK_UNCERTAIN: scheduling is blocked pending clock review.</p>}
    {(checked.pump_health !== null || checked.pump_status === 'TICK_FAILED') && <p role="alert">TICK_FAILED: the backup worker failed. Historical archives do not establish current worker health.</p>}
    {checked.pump_status === 'HEALTH_UNRECORDED' && <p role="alert">HEALTH_UNRECORDED: the worker failed and its health journal could not be written.</p>}
    <p>Last historical archive with complete member verification: {archive ? archive.archive + ' (' + archive.verification_kind + ')' : 'UNAVAILABLE'}. This is historical archive consistency evidence, not a successful recovery drill.</p>
    <p>Last verified recovery point: UNAVAILABLE. Recovery time, recovery-point objectives and key recovery are not established.</p>
    <p>Missed jobs recorded: {checked.missed_count}. Backup listings validate archive structure only; they do not refresh verification time.</p>
    {checked.last_job && <p>Last scheduled job: {checked.last_job.status} — {checked.last_job.reason || 'No terminal result yet'}.</p>}
    <ul aria-label="Recent scheduled backup jobs">{checked.history.map(job =>
      <li key={job.operation_id}>{job.operation_id}: {job.status}{job.reason ? ' — ' + job.reason : ''}</li>)}</ul>
  </>;
}
