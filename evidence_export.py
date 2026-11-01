"""R08 derived report evidence; original sources and audit baselines stay immutable.

Reduced means typed field selection, never anonymity. Standalone verification
checks package consistency; existing-index audit verification is a separate gate.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from session_contract import strict_json_loads

STORE = '.kinelab-evidence-exports'
SCHEMA = 'kinelab.evidence-export.v1'
RECEIPT = 'kinelab.evidence-export-receipt.v1'
STARTED = 'EVIDENCE_EXPORT_STARTED'
PUBLISHED = 'EVIDENCE_EXPORT_PUBLISHED'
LIMIT = 192 * 1024 * 1024
MANIFEST_LIMIT = 1024 * 1024
HEX = re.compile(r'[0-9a-f]{64}\Z')
OP = re.compile(r'[0-9a-f]{32}\Z')
EXPORT = re.compile(r'evidence-[0-9a-f]{32}\Z')
PROFILES = {'privacy-reduced', 'full'}
BASE_FIELDS = {'confirm', 'profile', 'operation_id', 'expected_report_head',
               'expected_report_context_sha256'}
MEMBERS = {'report.pdf', 'report-summary.json', 'metrics.csv', 'source-report-manifest.json'}


class EvidenceExportError(ValueError):
    """Closed, privacy-safe semantic refusal."""


class ExportRequestError(EvidenceExportError):
    """Malformed public request, mapped narrowly to HTTP 400."""


def _fail(code):
    raise EvidenceExportError(code + ': evidence export refused; originals preserved')


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _ref(raw):
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _hex(value, pattern=HEX):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _head(value):
    return (isinstance(value, dict) and set(value) == {'generation', 'manifest_sha256'}
            and isinstance(value['generation'], str)
            and re.fullmatch(r'report-[0-9a-f]{32}', value['generation']) is not None
            and _hex(value['manifest_sha256']))


def validate_request(value):
    if not isinstance(value, dict):
        raise ExportRequestError('EXPORT_REQUEST_INVALID: exact confirmed export request required')
    fields = BASE_FIELDS | ({'confirm_full'} if value.get('profile') == 'full' else set())
    if (set(value) != fields or value['confirm'] is not True
            or not isinstance(value['profile'], str) or value['profile'] not in PROFILES
            or not _hex(value['operation_id'], OP) or not _head(value['expected_report_head'])
            or not _hex(value['expected_report_context_sha256'])
            or (value['profile'] == 'full' and value['confirm_full'] is not True)):
        raise ExportRequestError('EXPORT_REQUEST_INVALID: exact confirmed export request required')
    return json.loads(_json(value))


def _read(path, limit, expected=None):
    from session_metadata_revision import MetadataRevisionError, _read_file
    try:
        raw, digest = _read_file(Path(path), limit=limit,
                                 expected_size=None if expected is None else expected['bytes'])
    except MetadataRevisionError as error:
        raise EvidenceExportError('EXPORT_SOURCE_INVALID: bounded ordinary bytes required') from error
    if expected is not None and {'sha256': digest, 'bytes': len(raw)} != expected:
        _fail('EXPORT_SOURCE_CHANGED')
    return raw


def _store(index):
    from take_acceptance import checked_path
    root = checked_path(index.projects_root)
    path = checked_path(root / STORE)
    # A dot administrative sibling is outside every supported session ID/root.
    if path.parent != root or path.name != STORE:
        _fail('EXPORT_DESTINATION_INVALID')
    if path.exists() and not path.is_dir():
        _fail('EXPORT_DESTINATION_INVALID')
    return path


def _path(index, export_id):
    from take_acceptance import local_path
    if not _hex(export_id, EXPORT):
        _fail('EXPORT_AUDIT_INVALID')
    return local_path(_store(index), export_id + '.zip')


def _select(index, sid, request):
    from report_generation import selected_report_generation
    try:
        return selected_report_generation(index, sid, request['expected_report_head'],
                                          request['expected_report_context_sha256'])
    except ValueError as error:
        code = str(error).partition(':')[0]
        if code == 'REPORT_CONTEXT_CHANGED':
            _fail('EXPORT_CONTEXT_CHANGED')
        raise EvidenceExportError('EXPORT_SOURCE_INVALID: verified current registered v2 report required') from error


def _records(index, sid):
    try:
        index.verify_audit()
        rows = index.conn.execute(
            'SELECT event_id,event_hash,event_type,details_json FROM audit_events '
            'WHERE session_id=? AND event_type IN (?,?) ORDER BY id LIMIT 1025',
            (sid, STARTED, PUBLISHED)).fetchall()
        if len(rows) > 1024:
            _fail('EXPORT_LIMIT')
        records = {}
        for row in rows:
            value = strict_json_loads(row['details_json'])
            if row['event_type'] == STARTED:
                if not isinstance(value, dict) or set(value) != {'schema', 'request', 'export_id'}:
                    _fail('EXPORT_AUDIT_INVALID')
                if value['schema'] != 'kinelab.evidence-export-intent.v1':
                    _fail('EXPORT_AUDIT_INVALID')
                request = validate_request(value['request'])
                operation = request['operation_id']
                if operation in records or not _hex(value['export_id'], EXPORT):
                    _fail('EXPORT_AUDIT_INVALID')
                records[operation] = {'request': request, 'export_id': value['export_id'], 'receipt': None}
            else:
                if not isinstance(value, dict) or set(value) != {'schema', 'receipt'} or value['schema'] != 'kinelab.evidence-export-publication.v1':
                    _fail('EXPORT_AUDIT_INVALID')
                receipt = value['receipt']
                _receipt_shape(receipt, sid)
                record = records.get(receipt['operation_id'])
                if (record is None or record['receipt'] is not None
                        or receipt['export_id'] != record['export_id']
                        or receipt['profile'] != record['request']['profile']
                        or receipt['report_head'] != record['request']['expected_report_head']
                        or receipt['report_context_sha256'] != record['request']['expected_report_context_sha256']):
                    _fail('EXPORT_AUDIT_INVALID')
                record['receipt'] = {**receipt, 'audit': {'event_id': row['event_id'], 'event_hash': row['event_hash']}}
        return records
    except EvidenceExportError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise EvidenceExportError('EXPORT_AUDIT_INVALID: malformed export audit') from error


def _reference(value):
    if (not isinstance(value, dict) or set(value) != {'sha256', 'bytes'}
            or not _hex(value['sha256']) or type(value['bytes']) is not int
            or not 0 <= value['bytes'] <= LIMIT):
        _fail('EXPORT_INVALID')


def _receipt_shape(value, sid):
    fields = {'schema', 'session_id', 'operation_id', 'export_id', 'profile', 'report_head',
              'report_context_sha256', 'manifest_sha256', 'archive'}
    if (not isinstance(value, dict) or set(value) != fields or value['schema'] != RECEIPT
            or value['session_id'] != sid or not _hex(value['operation_id'], OP)
            or not _hex(value['export_id'], EXPORT) or value['profile'] not in PROFILES
            or not _head(value['report_head']) or not _hex(value['report_context_sha256'])
            or not _hex(value['manifest_sha256'])):
        _fail('EXPORT_AUDIT_INVALID')
    _reference(value['archive'])


def _bundle(selection, request, export_id):
    source = strict_json_loads(selection['members']['report-summary.json'].decode('utf-8'))
    if (not isinstance(source, dict) or source.get('schema') != 'kinelab.research-report.v1'
            or type(source.get('is_test_only')) is not bool
            or type(source.get('measurement_count')) is not int or source['measurement_count'] < 0
            or source.get('clinical_accuracy_verified') is not False
            or source.get('physical_accuracy_verified') is not False):
        _fail('EXPORT_SOURCE_INVALID')
    classification = {'privacy': 'pseudonymous-linkable' if request['profile'] == 'privacy-reduced' else 'identified-linkable',
                      'is_test_only': source['is_test_only'], 'clinical_validation': 'UNVERIFIED',
                      'physical_validation': 'UNVERIFIED', 'anonymity_claimed': False}
    unavailable = {'status': 'UNAVAILABLE', 'reason': 'NO_SUPPORTED_BOUND_REPORT_CONTRACT'}
    projection = {'schema': 'kinelab.evidence-projection.v1', 'classification': classification,
                  'measurement_count': source['measurement_count'],
                  'units': unavailable, 'coordinate_definitions': unavailable,
                  'quality_and_gaps': unavailable, 'model': unavailable, 'calibration': unavailable}
    files = {'evidence.json': _json(projection)} if request['profile'] == 'privacy-reduced' else dict(selection['members'])
    context = selection['context']
    manifest = {'schema': SCHEMA, 'profile': request['profile'], 'export_id': export_id,
                'report_head': selection['head'], 'report_context_sha256': context['report_context_sha256'],
                'source_references': {name: context[name] for name in ('origin_sha256', 'run_sha256', 'metadata_context_sha256')},
                'manual_assessment_context_sha256': context['manual_assessment_context']['sha256'],
                'lineage': selection['lineage'], 'classification': classification,
                'formats': {'json': 'kinelab.evidence-projection.v1' if request['profile'] == 'privacy-reduced' else 'original-report-members',
                            'native_motion': 'UNAVAILABLE_UNSUPPORTED_ADAPTER', 'trc': 'UNAVAILABLE_UNSUPPORTED_ADAPTER',
                            'mot': 'UNAVAILABLE_UNSUPPORTED_ADAPTER'},
                'files': {name: _ref(raw) for name, raw in files.items()}}
    if sum(len(raw) for raw in files.values()) > LIMIT - MANIFEST_LIMIT:
        _fail('EXPORT_LIMIT')
    manifest_bytes = _json(manifest)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
        for name, raw in sorted(files.items()):
            archive.writestr(name, raw)
        archive.writestr('export-manifest.json', manifest_bytes)
    raw = stream.getvalue()
    verify_bytes(raw)
    return raw, _ref(manifest_bytes)['sha256']


def verify_bytes(raw):
    """Independent consistency only; no offline authenticated audit claim."""
    if not isinstance(raw, bytes) or len(raw) > LIMIT:
        _fail('EXPORT_LIMIT')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            infos = archive.infolist()
            names = [item.filename for item in infos]
            if (len(names) != len(set(names)) or len(names) > 5
                    or any(name not in MEMBERS | {'evidence.json', 'export-manifest.json'} for name in names)
                    or 'export-manifest.json' not in names
                    or any(item.compress_type != zipfile.ZIP_STORED or item.flag_bits & 1
                           or item.file_size > LIMIT
                           or ((item.external_attr >> 16) & 0o170000) not in (0, 0o100000)
                           for item in infos)
                    or sum(item.file_size for item in infos) > LIMIT):
                _fail('EXPORT_INVALID')
            contents = {}
            for item in infos:
                cap = MANIFEST_LIMIT if item.filename == 'export-manifest.json' else LIMIT
                if item.file_size > cap:
                    _fail('EXPORT_LIMIT')
                with archive.open(item) as stream:
                    content = stream.read(item.file_size + 1)
                if len(content) != item.file_size:
                    _fail('EXPORT_INVALID')
                contents[item.filename] = content
        document = strict_json_loads(contents['export-manifest.json'].decode('utf-8'))
        fields = {'schema', 'profile', 'export_id', 'report_head', 'report_context_sha256',
                  'source_references', 'manual_assessment_context_sha256', 'lineage',
                  'classification', 'formats', 'files'}
        if (not isinstance(document, dict) or set(document) != fields or document['schema'] != SCHEMA
                or not isinstance(document['profile'], str) or document['profile'] not in PROFILES
                or not _hex(document['export_id'], EXPORT) or not _head(document['report_head'])
                or not _hex(document['report_context_sha256']) or not _hex(document['manual_assessment_context_sha256'])):
            _fail('EXPORT_INVALID')
        references = document['source_references']
        if not isinstance(references, dict) or set(references) != {'origin_sha256', 'run_sha256', 'metadata_context_sha256'} or not all(_hex(item) for item in references.values()):
            _fail('EXPORT_INVALID')
        lineage = document['lineage']
        if not isinstance(lineage, dict) or set(lineage) != {'event_id', 'event_hash', 'previous_hash'} or not _hex(lineage['event_id'], OP) or not all(_hex(lineage[name]) for name in ('event_hash', 'previous_hash')):
            _fail('EXPORT_INVALID')
        classification = document['classification']
        privacy = 'pseudonymous-linkable' if document['profile'] == 'privacy-reduced' else 'identified-linkable'
        if (not isinstance(classification, dict) or set(classification) != {'privacy', 'is_test_only', 'clinical_validation', 'physical_validation', 'anonymity_claimed'}
                or classification['privacy'] != privacy or type(classification['is_test_only']) is not bool
                or classification['clinical_validation'] != 'UNVERIFIED' or classification['physical_validation'] != 'UNVERIFIED'
                or classification['anonymity_claimed'] is not False):
            _fail('EXPORT_INVALID')
        expected = {'evidence.json'} if document['profile'] == 'privacy-reduced' else MEMBERS
        if not isinstance(document['files'], dict) or set(document['files']) != expected or set(contents) != expected | {'export-manifest.json'}:
            _fail('EXPORT_INVALID')
        for name, reference in document['files'].items():
            _reference(reference)
            if _ref(contents[name]) != reference:
                _fail('EXPORT_CHANGED')
        formats = {'json': 'kinelab.evidence-projection.v1' if document['profile'] == 'privacy-reduced' else 'original-report-members',
                   'native_motion': 'UNAVAILABLE_UNSUPPORTED_ADAPTER', 'trc': 'UNAVAILABLE_UNSUPPORTED_ADAPTER',
                   'mot': 'UNAVAILABLE_UNSUPPORTED_ADAPTER'}
        if document['formats'] != formats:
            _fail('EXPORT_INVALID')
        if document['profile'] == 'privacy-reduced':
            projection = strict_json_loads(contents['evidence.json'].decode('utf-8'))
            unavailable = {'status': 'UNAVAILABLE', 'reason': 'NO_SUPPORTED_BOUND_REPORT_CONTRACT'}
            if (not isinstance(projection, dict) or set(projection) != {'schema', 'classification', 'measurement_count', 'units', 'coordinate_definitions', 'quality_and_gaps', 'model', 'calibration'}
                    or projection['schema'] != 'kinelab.evidence-projection.v1' or projection['classification'] != classification
                    or type(projection['measurement_count']) is not int or projection['measurement_count'] < 0
                    or any(projection[key] != unavailable for key in ('units', 'coordinate_definitions', 'quality_and_gaps', 'model', 'calibration'))):
                _fail('EXPORT_INVALID')
        else:
            original = strict_json_loads(contents['source-report-manifest.json'].decode('utf-8'))
            if (_ref(contents['source-report-manifest.json'])['sha256'] != document['report_head']['manifest_sha256']
                    or original.get('schema') != 'kinelab.report-generation.v2'
                    or original.get('generation') != document['report_head']['generation']
                    or original.get('report_context_sha256') != document['report_context_sha256']):
                _fail('EXPORT_INVALID')
            from report_generation import _validate_context
            fields = {'schema', 'session_id', 'generation', 'inputs', 'files', 'input_policy',
                      'supersedes', 'origin_sha256', 'run_sha256', 'metadata_context_sha256',
                      'manual_assessment_context', 'report_context_sha256'}
            if set(original) != fields:
                _fail('EXPORT_INVALID')
            _validate_context(original, original['session_id'])
            if (any(original[name] != references[name] for name in references)
                    or original['manual_assessment_context']['sha256'] != document['manual_assessment_context_sha256']):
                _fail('EXPORT_INVALID')
            summary = strict_json_loads(contents['report-summary.json'].decode('utf-8'))
            if (not isinstance(summary, dict) or summary.get('schema') != 'kinelab.research-report.v1'
                    or summary.get('is_test_only') is not classification['is_test_only']
                    or summary.get('clinical_accuracy_verified') is not False
                    or summary.get('physical_accuracy_verified') is not False):
                _fail('EXPORT_INVALID')
            sid = original.get('session_id')
            if not isinstance(sid, str):
                _fail('EXPORT_INVALID')
            if not isinstance(original['files'], dict) or set(original['files']) != {f'{sid}-research-report.pdf', f'{sid}-research-summary.json', f'{sid}-metrics.csv'}:
                _fail('EXPORT_INVALID')
            for name, suffix in (('report.pdf', 'research-report.pdf'), ('report-summary.json', 'research-summary.json'), ('metrics.csv', 'metrics.csv')):
                if original['files'].get(f'{sid}-{suffix}') != _ref(contents[name]):
                    _fail('EXPORT_INVALID')
        return {'schema': SCHEMA, 'ok': True, 'manifest': document,
                'manifest_sha256': _ref(contents['export-manifest.json'])['sha256'],
                'audit_authenticity': 'UNVERIFIED_OFFLINE'}
    except EvidenceExportError:
        raise
    except (zipfile.BadZipFile, UnicodeError, KeyError, TypeError, ValueError, AttributeError) as error:
        raise EvidenceExportError('EXPORT_INVALID: malformed evidence archive') from error


def _committed(index, sid, record):
    from report_generation import committed_reports
    receipt = record['receipt']
    if receipt is None:
        _fail('EXPORT_PENDING')
    committed_reports(index, sid)  # Historical reports and immutable inputs; audited additions remain allowed.
    raw = _read(_path(index, record['export_id']), LIMIT, receipt['archive'])
    observed = verify_bytes(raw)
    if (observed['manifest_sha256'] != receipt['manifest_sha256']
            or observed['manifest']['report_head'] != receipt['report_head']
            or observed['manifest']['report_context_sha256'] != receipt['report_context_sha256']
            or observed['manifest']['profile'] != receipt['profile']
            or observed['manifest']['export_id'] != receipt['export_id']):
        _fail('EXPORT_CHANGED')
    return receipt, raw


def publish(index, sid, value):
    from take_acceptance import acceptance_lease
    request = validate_request(value)
    project = index.library.open_session(sid)
    _store(index)  # Reject linked/invalid output roots without creating anything.
    with acceptance_lease(project):
        with index.transaction():
            records = _records(index, sid)
            previous = records.get(request['operation_id'])
            if previous is not None:
                if previous['request'] != request:
                    _fail('EXPORT_OPERATION_CONFLICT')
                return _committed(index, sid, previous)[0]
            if len(records) >= 512:
                _fail('EXPORT_LIMIT')
            selection = _select(index, sid, request)
            export_id = 'evidence-' + uuid4().hex
            raw, manifest_sha = _bundle(selection, request, export_id)
            index._append_audit(sid, STARTED, {'schema': 'kinelab.evidence-export-intent.v1',
                                             'request': request, 'export_id': export_id})
        store = _store(index)
        store.mkdir(exist_ok=True)
        destination = _path(index, export_id)
        with destination.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            import os
            os.fsync(stream.fileno())
        receipt = {'schema': RECEIPT, 'session_id': sid, 'operation_id': request['operation_id'],
                   'export_id': export_id, 'profile': request['profile'],
                   'report_head': selection['head'],
                   'report_context_sha256': request['expected_report_context_sha256'],
                   'manifest_sha256': manifest_sha, 'archive': _ref(raw)}
        with index.transaction():
            current = _records(index, sid).get(request['operation_id'])
            if current is None or current['receipt'] is not None or current['export_id'] != export_id or current['request'] != request:
                _fail('EXPORT_AUDIT_INVALID')
            _select(index, sid, request)  # Current source/head/context fence at commit.
            if _read(destination, LIMIT, receipt['archive']) != raw:
                _fail('EXPORT_CHANGED')
            index._append_audit(sid, PUBLISHED, {'schema': 'kinelab.evidence-export-publication.v1', 'receipt': receipt})
        with index.read_snapshot():
            return _committed(index, sid, _records(index, sid)[request['operation_id']])[0]


def read_receipt(index, sid, operation_id, *, artifact=False):
    if not _hex(operation_id, OP):
        _fail('EXPORT_REQUEST_INVALID')
    index.library.open_session(sid)
    with index.read_snapshot():
        record = _records(index, sid).get(operation_id)
        if record is None:
            _fail('EXPORT_UNAVAILABLE')
        receipt, raw = _committed(index, sid, record)
        return raw if artifact else receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description='Read-only R08 report evidence package consistency verifier')
    parser.add_argument('command', choices=('verify',))
    parser.add_argument('archive')
    args = parser.parse_args(argv)
    try:
        result = verify_bytes(_read(Path(args.archive), LIMIT))
        print(json.dumps({'schema': SCHEMA, 'ok': True, 'audit_authenticity': result['audit_authenticity'],
                          'manifest_sha256': result['manifest_sha256']}, allow_nan=False))
        return 0
    except EvidenceExportError as error:
        print(json.dumps({'schema': SCHEMA, 'ok': False, 'error': str(error)}, allow_nan=False))
        return 1
    except OSError:
        print(json.dumps({'schema': SCHEMA, 'ok': False, 'error': 'EXPORT_IO: ordinary readable archive required'}, allow_nan=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())