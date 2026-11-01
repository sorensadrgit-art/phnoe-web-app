"""Immutable report generations; SQLite audit commit is publication authority."""
import hashlib
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from session_contract import sha256_file, strict_json_loads

GENERATION = re.compile(r'report-[0-9a-f]{32}')
INPUT_POLICY_V2 = 'kinelab.report-inputs.v2'
ADMINISTRATIVE_ANCHOR = 'takes/.acceptance-lease/t6-startup.lock'
OMITTED = object()
MANIFEST_V2 = 'kinelab.report-generation.v2'


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _reference(value):
    if (not isinstance(value, dict) or set(value) != {'sha256', 'bytes'}
            or not isinstance(value['sha256'], str)
            or re.fullmatch(r'[0-9a-f]{64}', value['sha256']) is None
            or type(value['bytes']) is not int or value['bytes'] < 0):
        raise ValueError('REPORT_INVALID: invalid content reference')
    return value


def _file(folder, relative):
    from take_acceptance import local_path
    path = local_path(folder, relative)
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError('REPORT_INVALID: ordinary file required')
    digest = sha256_file(path)
    after = path.stat(follow_symlinks=False)
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size,
                             item.st_mtime_ns, item.st_ctime_ns, item.st_mode)
    if identity(before) != identity(after):
        raise ValueError('REPORT_SOURCE_CHANGED: file changed while hashing')
    return {'sha256': digest, 'bytes': after.st_size}


def _linked(path):
    try:
        attributes = getattr(path.lstat(), 'st_file_attributes', 0)
    except FileNotFoundError:
        return False
    return (path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
            or bool(attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT))


def _input_policy(document):
    # Only an absent field selects the original strict inventory contract.
    policy = document.get('input_policy')
    if 'input_policy' in document and policy != INPUT_POLICY_V2:
        raise ValueError('unsupported report input policy')
    if not isinstance(document['inputs'], dict):
        raise TypeError('invalid report input inventory')
    if policy == INPUT_POLICY_V2 and ADMINISTRATIVE_ANCHOR in document['inputs']:
        raise ValueError('v2 report records an excluded administrative anchor')
    return policy


def capture_inputs(folder, *, input_policy=INPUT_POLICY_V2):
    """Bind sources under the declared policy; None retains strict legacy v1."""
    if input_policy not in (None, INPUT_POLICY_V2):
        raise ValueError('REPORT_INVALID: unsupported report input policy')
    result = {}
    if _linked(folder) or _linked(folder / 'exports'):
        raise ValueError('REPORT_INVALID: linked session or exports')
    anchor = folder / ADMINISTRATIVE_ANCHOR
    if _linked(anchor) or (anchor.exists() and not anchor.is_file()):
        raise ValueError('REPORT_INVALID: nonregular administrative anchor')
    for root, dirs, files in os.walk(folder):
        root = Path(root)
        if any(_linked(root / name) for name in dirs + files):
            raise ValueError('REPORT_INVALID: linked report input')
        if root == folder / 'exports':
            dirs[:] = [name for name in dirs if not GENERATION.fullmatch(name)
                       and not name.startswith('.report-staging-')]
        for name in sorted(files):
            path = root / name
            if not path.is_file():
                raise ValueError('REPORT_INVALID: non-file input')
            relative = path.relative_to(folder).as_posix()
            if input_policy == INPUT_POLICY_V2 and relative == ADMINISTRATIVE_ANCHOR:
                continue
            result[relative] = _file(folder, relative)
            if len(result) > 10000:
                raise ValueError('REPORT_INVALID: source inventory exceeds supported limit')
    return result


def _history(index, session_id):
    """Integrity is independent of whether a generation is currently applicable."""
    folder = index.library.open_session(session_id)
    index.verify_audit()
    rows = index.conn.execute("SELECT id,details_json FROM audit_events WHERE session_id=? AND event_type='REPORT_PUBLISHED' ORDER BY id LIMIT 513", (session_id,)).fetchall()
    if len(rows) > 512:
        raise ValueError('REPORT_INVALID: generation verification limit exceeded')
    history, seen = [], set()
    previous = None
    for row in rows:
        try:
            receipt = strict_json_loads(row['details_json'])
            generation = receipt['generation']
            if (not isinstance(generation, str) or GENERATION.fullmatch(generation) is None
                    or generation in seen):
                raise ValueError('generation identity')
            seen.add(generation)
            directory = folder / 'exports' / generation
            raw, reference = read_report_bytes(folder, f'exports/{generation}/manifest.json',
                                               limit=8 * 1024 * 1024)
            if reference['sha256'] != receipt['manifest_sha256']:
                raise ValueError('manifest digest or limit')
            document = strict_json_loads(raw.decode('utf-8'))
            base = {'schema', 'session_id', 'generation', 'inputs', 'files'}
            v2 = document.get('schema') == MANIFEST_V2
            fields = base | {'input_policy', 'supersedes', 'origin_sha256', 'run_sha256',
                             'metadata_context_sha256', 'manual_assessment_context', 'report_context_sha256'}
            if v2:
                if set(document) != fields or set(receipt) != {'schema', 'generation', 'manifest_sha256', 'supersedes', 'report_context_sha256'}:
                    raise ValueError('v2 exact fields')
                if (receipt['schema'] != 'kinelab.report-publication.v2'
                        or document['supersedes'] != previous or receipt['supersedes'] != previous
                        or receipt['report_context_sha256'] != document['report_context_sha256']):
                    raise ValueError('publication lineage')
                _validate_context({key: document[key] for key in ('input_policy', 'inputs', 'origin_sha256', 'run_sha256', 'metadata_context_sha256', 'manual_assessment_context', 'report_context_sha256')}, session_id)
            elif (document.get('schema') != 'kinelab.report-generation.v1'
                  or set(document) not in (base, base | {'input_policy'})
                  or set(receipt) != {'generation', 'manifest_sha256'} or previous is not None):
                raise ValueError('legacy manifest or lineage')
            if document['session_id'] != session_id or document['generation'] != generation:
                raise ValueError('manifest identity')
            _input_policy(document)
            for relative, item in document['inputs'].items():
                from take_acceptance import local_path
                local_path(folder, relative)
                _reference(item)
            names = {f'{session_id}-research-report.pdf', f'{session_id}-research-summary.json', f'{session_id}-metrics.csv'}
            if (not isinstance(document['files'], dict) or set(document['files']) != names
                    or {path.name for path in directory.iterdir()} != names | {'manifest.json'}):
                raise ValueError('incomplete report set')
            entries = []
            for name, item in {**document['files'], 'manifest.json': reference}.items():
                _reference(item)
                key = f'exports/{generation}/{name}'
                registered = index.conn.execute('SELECT sha256,bytes FROM artifacts WHERE session_id=? AND artifact_key=?', (session_id, key)).fetchone()
                if (registered is None or registered['sha256'] != item['sha256']
                        or registered['bytes'] != item['bytes']
                        or read_report_bytes(folder, key, limit=item['bytes'], expected=item, collect=False)[1] != item):
                    raise ValueError('report file or registration changed')
                if name != 'manifest.json':
                    entries.append({'filename': name, 'key': key, 'type': 'research_report', 'bytes': item['bytes']})
            previous = {'generation': generation, 'manifest_sha256': reference['sha256']}
            history.append({'id': row['id'], 'head': previous, 'document': document, 'entries': entries})
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            raise ValueError('REPORT_INVALID: incomplete or changed committed generation') from exc
    return history


def _validate_context(value, session_id):
    for name in ('origin_sha256', 'run_sha256', 'metadata_context_sha256', 'report_context_sha256'):
        if not isinstance(value[name], str) or re.fullmatch(r'[0-9a-f]{64}', value[name]) is None:
            raise ValueError('REPORT_INVALID: context digest')
    manual = value['manual_assessment_context']
    if (not isinstance(manual, dict) or set(manual) != {'schema', 'assessments', 'unavailable_assessments', 'sha256'}
            or manual['schema'] != 'kinelab.report-manual-context.v1'
            or not isinstance(manual['assessments'], list) or not isinstance(manual['unavailable_assessments'], list)
            or manual['sha256'] != _digest({key: item for key, item in manual.items() if key != 'sha256'})):
        raise ValueError('REPORT_INVALID: manual context')
    operations = []
    for receipt in manual['assessments']:
        if (not isinstance(receipt, dict) or set(receipt) != {'schema', 'session_id', 'operation_id', 'metadata_context_sha256', 'descriptor', 'test_only', 'clinical_accuracy_validated'}
                or receipt['schema'] != 'kinelab.manual-assessment-entry-receipt.v1'
                or receipt['session_id'] != session_id or receipt['test_only'] is not True
                or receipt['clinical_accuracy_validated'] is not False
                or receipt['metadata_context_sha256'] != value['metadata_context_sha256']):
            raise ValueError('REPORT_INVALID: manual receipt projection')
        operation = receipt['operation_id']
        descriptor = receipt['descriptor']
        if (not isinstance(operation, str) or re.fullmatch(r'[0-9a-f]{32}', operation) is None
                or not isinstance(descriptor, dict) or set(descriptor) != {'path', 'sha256'}
                or descriptor['path'] != f'exports/manual-entry-{operation}.manual-assessment.json'
                or not isinstance(descriptor['sha256'], str)
                or re.fullmatch(r'[0-9a-f]{64}', descriptor['sha256']) is None):
            raise ValueError('REPORT_INVALID: manual descriptor projection')
        operations.append(operation)
    if operations != sorted(set(operations)):
        raise ValueError('REPORT_INVALID: manual receipt order or duplicates')
    unavailable = []
    for item in manual['unavailable_assessments']:
        if (not isinstance(item, dict) or set(item) != {'operation_id', 'reason'}
                or item['reason'] != 'METADATA_CONTEXT_CHANGED'
                or not isinstance(item['operation_id'], str)
                or re.fullmatch(r'[0-9a-f]{32}', item['operation_id']) is None):
            raise ValueError('REPORT_INVALID: unavailable manual projection')
        unavailable.append(item['operation_id'])
    if unavailable != sorted(set(unavailable)) or set(operations) & set(unavailable):
        raise ValueError('REPORT_INVALID: unavailable manual order or duplicates')
    projection = {'schema': 'kinelab.report-context.v1', 'session_id': session_id,
                  **{key: value[key] for key in ('input_policy', 'inputs', 'origin_sha256', 'run_sha256', 'metadata_context_sha256', 'manual_assessment_context')}}
    if value['input_policy'] != INPUT_POLICY_V2 or value['report_context_sha256'] != _digest(projection):
        raise ValueError('REPORT_INVALID: report context')


def _registered(index, session_id, folder):
    import session_metadata_revision as metadata
    from take_acceptance import local_path
    origin = local_path(folder, 'session.json')
    if not origin.exists():
        return None
    document, _ = metadata._document(origin)
    # Historical generated/demo projects without registered captures retain v1.
    if document.get('schema') != 'kinelab.session.v1' or 'captures' not in document:
        if document.get('kind') == 'real':
            raise ValueError('REPORT_INVALID: registered metadata unavailable')
        return None
    return metadata._resolved(index, session_id, folder)


def _evidence(index, session_id, folder, resolved):
    """Only exact validator-reached files acquire audited-addition authority."""
    import manual_assessment_entry as entry
    import session_metadata_revision as metadata
    from take_acceptance import local_path
    state, _, operations, _ = resolved
    authority = {}
    def allow(relative, event_id):
        authority[relative] = (_file(folder, relative), event_id)
    rows = index.conn.execute('SELECT id,event_type,details_json FROM audit_events WHERE session_id=? AND event_type IN (?,?) ORDER BY id',
                              (session_id, metadata.EVENT, entry.EVENT)).fetchall()
    records = entry._events(index, session_id)
    session, _ = metadata._document(local_path(folder, 'session.json'))
    receipts = []
    for row in rows:
        record = strict_json_loads(row['details_json'])
        if row['event_type'] == metadata.EVENT:
            operation = record['operation_id']
            if operation not in operations:
                raise ValueError('REPORT_INVALID: metadata publication unavailable')
            allow(record['descriptor']['path'], row['id'])
            terminal = f'metadata-revisions/resolved-{operation}-committed.json'
            if local_path(folder, terminal).exists():
                allow(terminal, row['id'])
        else:
            operation = record['request']['operation_id']
            receipt = entry._verify_entry(folder, session_id, records[operation], session)
            receipts.append(receipt)
            relative = receipt['descriptor']['path']
            descriptor, _, _ = entry._document(local_path(folder, relative))
            allow(relative, row['id'])
            allow(f'assessment-entries/entry-{operation}/reference.json', row['id'])
            for binding in descriptor['inputs'].values():
                allow(binding['snapshot']['path'], row['id'])
            copied = relative.removesuffix('.manual-assessment.json') + '.manual-assessment-inputs/descriptor.json'
            if _file(folder, copied) != _file(folder, relative):
                raise ValueError('REPORT_INVALID: manual descriptor snapshot changed')
            allow(copied, row['id'])
    manual = {'schema': 'kinelab.report-manual-context.v1',
              'assessments': sorted((item for item in receipts if item['metadata_context_sha256'] == state['context_sha256']), key=lambda item: item['operation_id']),
              'unavailable_assessments': sorted(({'operation_id': item['operation_id'], 'reason': 'METADATA_CONTEXT_CHANGED'} for item in receipts if item['metadata_context_sha256'] != state['context_sha256']), key=lambda item: item['operation_id'])}
    manual['sha256'] = _digest(manual)
    return authority, manual


def _current(index, session_id, history):
    folder = index.library.open_session(session_id)
    resolved = _registered(index, session_id, folder)
    if resolved is None:
        raise ValueError('REPORT_CONTEXT_UNAVAILABLE: registered metadata required')
    state = resolved[0]
    authority, manual = _evidence(index, session_id, folder, resolved)
    inputs = capture_inputs(folder)
    _check_inputs(index, session_id, history, authority)
    run = _file(folder, 'run.json')
    from run_pipeline import validate_run_evidence
    validate_run_evidence(folder, through='poseEstimation')
    value = {'schema': 'kinelab.report-context.v1', 'session_id': session_id,
             'input_policy': INPUT_POLICY_V2, 'inputs': inputs,
             'origin_sha256': state['origin']['sha256'], 'run_sha256': run['sha256'],
             'metadata_context_sha256': state['context_sha256'], 'manual_assessment_context': manual}
    value['report_context_sha256'] = _digest(value)
    return value


def _check_inputs(index, session_id, history, authority=None):
    folder = index.library.open_session(session_id)
    for item in history:
        document = item['document']
        current = capture_inputs(folder, input_policy=_input_policy(document))
        baseline = document['inputs']
        if current == baseline:
            continue
        if (document.get('input_policy') is None and ADMINISTRATIVE_ANCHOR not in baseline
                and ADMINISTRATIVE_ANCHOR in current
                and {key: value for key, value in current.items() if key != ADMINISTRATIVE_ANCHOR} == baseline):
            raise ValueError('REPORT_INPUT_POLICY_COMPATIBILITY_REQUIRED: legacy report did not bind the later administrative anchor; explicit migration is required')
        if authority is None:
            resolved = _registered(index, session_id, folder)
            if resolved is None:
                raise ValueError('REPORT_SOURCE_CHANGED: report inputs no longer match their published revision')
            authority = _evidence(index, session_id, folder, resolved)[0]
        if any(current.get(key) != reference for key, reference in baseline.items()):
            raise ValueError('REPORT_SOURCE_CHANGED: report inputs no longer match their published revision (published input changed or removed)')
        for key in current.keys() - baseline.keys():
            authorized = authority.get(key)
            if authorized is None or authorized[0] != current[key] or authorized[1] <= item['id']:
                raise ValueError('REPORT_SOURCE_CHANGED: report inputs no longer match their published revision (unaudited input addition)')


def current_report_context(index, session_id):
    """Portable content-only observation; no directory, anchor or audit writes."""
    with index.read_snapshot():
        return _current(index, session_id, _history(index, session_id))


def current_report_generation_context(index, session_id):
    """Project the verified context and lineage head from one read snapshot."""
    with index.read_snapshot():
        history = _history(index, session_id)
        current = _current(index, session_id, history)
        return {'schema': 'kinelab.report-generation-context.v1',
                'session_id': session_id, 'status': 'AVAILABLE',
                'report_context_sha256': current['report_context_sha256'],
                'head': history[-1]['head'] if history else None, 'reason': None}


def committed_reports(index, session_id, *, check_inputs=True):
    with index.read_snapshot():
        history = _history(index, session_id)
        if check_inputs:
            _check_inputs(index, session_id, history)
        return [entry for item in history for entry in item['entries']]


def publication_context(index, session_id, expected_report_head=OMITTED, expected_report_context_sha256=OMITTED):
    """Preflight before staging; caller owns the one session lease for publication."""
    with index.read_snapshot():
        history = _history(index, session_id)
        if len(history) >= 512:
            raise ValueError('REPORT_INVALID: generation publication limit exceeded')
        folder = index.library.open_session(session_id)
        resolved = _registered(index, session_id, folder)
        if resolved is None:
            if history or expected_report_head is not OMITTED or expected_report_context_sha256 is not OMITTED:
                raise ValueError('OUTPUT_EXISTS: legacy reports are immutable')
            return None, None
        context = _current(index, session_id, history)
        head = history[-1]['head'] if history else None
        supplied = expected_report_head is not OMITTED or expected_report_context_sha256 is not OMITTED
        if (history or supplied) and (expected_report_head is OMITTED or expected_report_context_sha256 is OMITTED
                or expected_report_head != head or expected_report_context_sha256 != context['report_context_sha256']):
            raise ValueError('REPORT_CONTEXT_CHANGED: exact head and context required')
        if history and history[-1]['document'].get('report_context_sha256') == context['report_context_sha256']:
            raise ValueError('OUTPUT_EXISTS: report context unchanged')
        return context, head


def publish_reports(index, session_id, staging, outputs, inputs, *, context=None, supersedes=None):
    if os.name != 'nt':
        raise ValueError('REPORT_PLATFORM_UNVERIFIED: no-overwrite directory publication is verified on Windows only')
    folder = index.library.open_session(session_id)
    generation = 'report-' + uuid4().hex
    target = folder / 'exports' / generation
    files = {path.name: _file(staging, path.name) for path in outputs.values()}
    document = {'schema': 'kinelab.report-generation.v1', 'generation': generation,
                'session_id': session_id, 'input_policy': INPUT_POLICY_V2, 'inputs': inputs, 'files': files}
    if context is not None:
        document.update(schema=MANIFEST_V2, supersedes=supersedes,
                        **{key: context[key] for key in ('origin_sha256', 'run_sha256', 'metadata_context_sha256', 'manual_assessment_context', 'report_context_sha256')})
    manifest = staging / 'manifest.json'
    encoded = json.dumps(document, sort_keys=True, allow_nan=False).encode('utf-8')
    if len(encoded) > 8 * 1024 * 1024:
        raise ValueError('REPORT_INVALID: manifest exceeds supported limit')
    with manifest.open('xb') as stream:
        stream.write(encoded)
    for path in (*outputs.values(), manifest):
        with path.open('r+b') as handle:
            os.fsync(handle.fileno())
    now = datetime.now(UTC).isoformat()
    with index.transaction():
        history = _history(index, session_id)
        head = history[-1]['head'] if history else None
        if context is None:
            if history:
                raise ValueError('OUTPUT_EXISTS: legacy report is immutable')
        elif head != supersedes or _current(index, session_id, history) != context:
            raise ValueError('REPORT_CONTEXT_CHANGED: report changed during rendering')
        if capture_inputs(folder) != inputs:
            raise ValueError('REPORT_SOURCE_CHANGED: inputs changed during rendering')
        for path in (*outputs.values(), manifest):
            digest = sha256_file(path)
            index.conn.execute('''INSERT INTO artifacts
                (session_id,artifact_key,filename,artifact_type,bytes,sha256,created_at_utc,observed_sha256,integrity_state)
                VALUES (?,?,?,?,?,?,?,?,?)''', (session_id, f'exports/{generation}/{path.name}', path.name,
                    'research_report', path.stat().st_size, digest, now, digest, 'unchanged'))
        receipt = {'generation': generation, 'manifest_sha256': sha256_file(manifest)}
        if context is not None:
            receipt.update(schema='kinelab.report-publication.v2', supersedes=supersedes,
                           report_context_sha256=context['report_context_sha256'])
        index._append_audit(session_id, 'REPORT_PUBLISHED', receipt)
        os.rename(staging, target)
        if capture_inputs(folder) != inputs:
            raise ValueError('REPORT_SOURCE_CHANGED: inputs changed during publication')
        if context is not None and _current(index, session_id, _history(index, session_id)) != context:
            raise ValueError('REPORT_CONTEXT_CHANGED: context changed during publication')
    return {kind: target / path.name for kind, path in outputs.items()}


def read_report_bytes(folder, relative, *, limit, expected=None, collect=True):
    """Read one ordinary contained file once; hash/parse share bounded bytes."""
    from session_metadata_revision import MetadataRevisionError, _read_file
    from take_acceptance import local_path
    if expected is not None:
        _reference(expected)
        if expected['bytes'] > limit:
            raise ValueError('REPORT_INVALID: report member exceeds supported limit')
    try:
        raw, digest = _read_file(local_path(folder, relative), limit=limit,
                                 expected_size=None if expected is None else expected['bytes'],
                                 collect=collect)
    except MetadataRevisionError as error:
        raise ValueError('REPORT_INVALID: unstable or oversized report member') from error
    reference = {'sha256': digest, 'bytes': len(raw) if collect else expected['bytes']}
    if expected is not None and reference != expected:
        raise ValueError('REPORT_INVALID: report member digest differs')
    return raw, reference


def selected_report_generation(index, session_id, expected_head, expected_context):
    """Internal export authority; caller holds the existing session OS lease.

    Keep original report/current-source validators and all historical generations.
    Return bounded exact member bytes, never user-selected paths or healed baselines.
    """
    with index.read_snapshot():
        history = _history(index, session_id)
        if not history or history[-1]['document'].get('schema') != MANIFEST_V2:
            raise ValueError('REPORT_CONTEXT_UNAVAILABLE: registered v2 report required')
        latest = history[-1]
        current = _current(index, session_id, history)
        if (latest['head'] != expected_head
                or current['report_context_sha256'] != expected_context
                or latest['document']['report_context_sha256'] != expected_context):
            raise ValueError('REPORT_CONTEXT_CHANGED: current report head and context required')
        folder = index.library.open_session(session_id)
        generation = latest['head']['generation']
        members = {}
        caps = {'report.pdf': 128 * 1024 * 1024,
                'report-summary.json': 16 * 1024 * 1024, 'metrics.csv': 16 * 1024 * 1024}
        for target, suffix in (('report.pdf', 'research-report.pdf'),
                               ('report-summary.json', 'research-summary.json'),
                               ('metrics.csv', 'metrics.csv')):
            name = f'{session_id}-{suffix}'
            members[target] = read_report_bytes(
                folder, f'exports/{generation}/{name}', limit=caps[target],
                expected=latest['document']['files'][name])[0]
        raw, reference = read_report_bytes(folder, f'exports/{generation}/manifest.json',
                                           limit=8 * 1024 * 1024)
        if reference['sha256'] != expected_head['manifest_sha256']:
            raise ValueError('REPORT_INVALID: selected manifest changed')
        members['source-report-manifest.json'] = raw
        event = index.conn.execute(
            'SELECT event_id,event_hash,previous_hash FROM audit_events WHERE id=? AND session_id=?',
            (latest['id'], session_id)).fetchone()
        return {'head': latest['head'], 'context': current, 'members': members,
                'lineage': dict(event)}
