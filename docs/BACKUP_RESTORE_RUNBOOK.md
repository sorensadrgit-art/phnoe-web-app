# KineLab PT — Staged Backup & Restore Runbook

## 1. Overview
KineLab PT provides an offline, verifiable backup and restore subsystem (`backup_manager.py`) designed to prevent data loss, ensure reproducible research archives, and protect against filesystem corruption.

## 2. Backup Architecture & Format
- **Container**: Standard `.zip` archive named `kinelab-backup-<timestamp>-<uuid>.zip`.
- **Destination**: `%LOCALAPPDATA%\KineLabPT\backups\` (or user-specified backup volume).
- **Archive Contents**:
  - `index.db`: Clean online snapshot of the SQLite session index using the SQLite Online Backup API (`sqlite3.Connection.backup`).
  - `sessions/<session_id>/...`: Complete session folders, including metadata, configs, derived TRC/MOT data, and report files.
  - `backup_manifest.json`: Cryptographic manifest containing SHA-256 digests and byte counts for every file in the backup.

## 3. Creating a Backup

### Via Web Interface
1. Navigate to **Reports & History** in the KineLab PT workspace.
2. Under **Backup & Disaster Recovery**, click **Create New Backup**.
3. The system generates the archive, validates all hashes, and presents the completed backup entry with file size and timestamp.

### Via Command Line / Python
```python
from pathlib import Path
from backup_manager import BackupManager
from session_index import SessionIndex

projects_dir = Path("C:/Users/soren/Documents/Projects/KineLab-PT-DualCam/projects")
index = SessionIndex()
manager = BackupManager(projects_dir, index=index)

manifest = manager.create_backup(label="Manual research checkpoint")
print(f"Backup created: {manifest['backup_name']}, files: {manifest['total_files']}")
```

## 4. Staged Atomic Restore Procedure

Restores in KineLab PT follow a strict 4-phase staging protocol to ensure that partial or corrupt backups can NEVER overwrite active research data.

### Phase 1: Archive Extraction & Pre-Validation
1. An isolated staging directory is created: `.restore-staging-<uuid>`.
2. The backup archive is unpacked into the staging directory.
3. `backup_manifest.json` is located and parsed.

### Phase 2: 100% SHA-256 Verification
1. Every extracted file is hashed with SHA-256.
2. The computed hash is compared to the expected hash in `backup_manifest.json`.
3. If **any** file is missing, modified, or has a mismatched hash:
   - The restore operation **aborts immediately**.
   - An exception is raised.
   - The staging directory is purged.
   - Active data is completely untouched.

### Phase 3: Live Data Backup & Pre-Cutover
1. An automatic safety snapshot of current active sessions and database is generated.

### Phase 4: Atomic Commit & Index Rebuild
1. Validated session folders from staging are moved into `projects/`.
2. The SQLite database is restored from `index.db`.
3. The database connection is refreshed and audit logs record the restore event.
4. The staging directory is deleted.

## 5. Disaster Recovery
If the SQLite index database (`.kinelab_index.db`) becomes inaccessible or corrupted:
1. Delete or rename `.kinelab_index.db`.
2. Run `python -c "from session_index import SessionIndex; idx = SessionIndex(); count = idx.reindex_all(); print(f'Indexed {count} sessions')"`
3. The index will scan all session directories in `projects/`, extract metadata and state, and rebuild the database idempotently.
