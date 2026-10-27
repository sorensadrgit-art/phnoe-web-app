#requires -Version 5.1
<#
    KineLab PT DualCam - Gate G0 preflight, inventory, baseline capture, rollback snapshot.

    !!! UNEXECUTED !!!  This script has never been run. It was written without access to
    the workstation it targets, so its syntax and behaviour have NOT been validated on a
    real machine. Review it before use, and start with the audit-only path:

        powershell -ExecutionPolicy Bypass -File .\g0_preflight.ps1 -SkipTests -SkipSnapshot

    Safety properties by construction:
      * read-only with respect to projects\ and every media file (hash only; never
        written, moved, renamed or deleted)
      * no git reset, no git push, no --force, no branch deletion, no file deletion
      * the snapshot copy excludes media, models, databases, dependencies and .git;
        git history is preserved separately as a bundle of all refs

    Exit codes:
        0  G0 PASSED
        2  G0 PASSED WITH WARNINGS (a baseline or optional step failed)
        3  STOP (at least one STOP finding)
        5  STOP (project root not accessible; nothing read or written)
#>
[CmdletBinding()]
param(
    [string] $ProjectRoot    = 'C:\Users\soren\Documents\Projects\KineLab-PT-DualCam',
    [string] $SnapshotRoot,
    [string] $PythonExe      = 'python',
    [string] $PythonTestArgs = '-m pytest -q',
    [string] $JsTestCommand,
    [string] $BuildCommand,
    [string] $CompareMediaManifest,
    [string] $BranchName     = 'feature/kinelab-v1-finalization',
    [switch] $SkipTests,
    [switch] $SkipSnapshot,
    [switch] $CreateBranch,
    [switch] $WriteDocsIntoProject
)

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$script:Findings = New-Object System.Collections.ArrayList
$script:Phase    = 'init'
$stamp           = Get-Date -Format 'yyyyMMdd-HHmmss'

function Add-Finding {
    param([string]$Phase, [string]$Check, [string]$Status, [string]$Detail)
    [void]$script:Findings.Add([pscustomobject]@{
        phase = $Phase; check = $Check; status = $Status; detail = $Detail
    })
    $colour = switch ($Status) {
        'PASS'  { 'Green' }
        'FAIL'  { 'Red' }
        'STOP'  { 'Red' }
        default { 'Yellow' }
    }
    Write-Host ('  [{0,-5}] {1}: {2}' -f $Status, $Check, $Detail) -ForegroundColor $colour
}

# Runs an external command, captures merged output and exit code, optionally logs to file.
function Invoke-Tool {
    param(
        [Parameter(Mandatory)][string] $Exe,
        [string[]] $ArgList = @(),
        [string]   $WorkDir = (Get-Location).Path,
        [string]   $OutFile
    )
    $result = [pscustomobject]@{ exitCode = -1; output = @(); command = '' }
    $result.command = ($Exe + ' ' + ($ArgList -join ' '))
    $previous = (Get-Location).Path
    try {
        Set-Location -LiteralPath $WorkDir
        $result.output = & $Exe @ArgList 2>&1 | ForEach-Object { [string]$_ }
        $result.exitCode = $LASTEXITCODE
    }
    catch {
        $result.output = @($_.Exception.Message)
        $result.exitCode = -1
    }
    finally {
        Set-Location -LiteralPath $previous
    }
    if ($OutFile) {
        $result.output | Set-Content -LiteralPath $OutFile -Encoding UTF8
    }
    return $result
}

function Get-Sha256 {
    param([Parameter(Mandatory)][string] $Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Get-FileManifest {
    param(
        [Parameter(Mandatory)][string] $Root,
        [string[]] $Extensions,
        [string[]] $ExcludeDirNames = @()
    )
    $items = New-Object System.Collections.ArrayList
    $files = Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue
    foreach ($f in $files) {
        $full = $f.FullName
        $skip = $false
        foreach ($d in $ExcludeDirNames) {
            if ($full -like ('*\' + $d + '\*')) { $skip = $true; break }
        }
        if ($skip) { continue }
        if ($Extensions -and ($Extensions -notcontains $f.Extension.ToLowerInvariant())) { continue }
        [void]$items.Add([pscustomobject]@{
            relativePath = $full.Substring($Root.Length).TrimStart('\')
            bytes        = $f.Length
            sha256       = (Get-Sha256 -Path $full)
            lastWriteUtc = $f.LastWriteTimeUtc.ToString('o')
        })
    }
    return $items
}

$git = [pscustomobject]@{
    isRepo = $false; branch = ''; head = ''; dirty = $false; remotes = ''
}

$verdict = 'INCOMPLETE'
$runDir  = $null

try {
    # ---------------------------------------------------------------- G0.0 preflight
    $script:Phase = 'preflight'
    Write-Host "`n== G0.0 preflight ==" -ForegroundColor Cyan

    if (-not (Test-Path -LiteralPath $ProjectRoot -PathType Container)) {
        Write-Host "STOP: project root not accessible: $ProjectRoot" -ForegroundColor Red
        exit 5
    }
    $ProjectRoot = [IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    if (-not $SnapshotRoot) {
        $SnapshotRoot = Join-Path (Split-Path $ProjectRoot -Parent) 'KineLab-G0-Snapshots'
    }
    $runDir = Join-Path $SnapshotRoot ('g0-' + $stamp)
    New-Item -ItemType Directory -Path $runDir -Force | Out-Null

    Add-Finding 'preflight' 'project-root' 'PASS' $ProjectRoot
    Add-Finding 'preflight' 'run-dir'      'PASS' $runDir

    $driveLetter = (Split-Path $ProjectRoot -Qualifier).TrimEnd(':')
    $freeGB = 0
    try { $freeGB = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 2) } catch { }
    Add-Finding 'preflight' 'disk-free' $(if ($freeGB -lt 5) { 'FAIL' } else { 'PASS' }) "$freeGB GB free"

    # ---------------------------------------------------------------- G0.1 git state
    $script:Phase = 'git'
    Write-Host "`n== G0.1 git state (read-only) ==" -ForegroundColor Cyan
    $gitDir = Join-Path $runDir 'git'
    New-Item -ItemType Directory -Path $gitDir -Force | Out-Null

    $probe = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'rev-parse', '--is-inside-work-tree')
    if ($probe.exitCode -eq 0) {
        $git.isRepo = $true
        $headRes   = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'rev-parse', 'HEAD') -OutFile (Join-Path $gitDir 'head.txt')
        $git.head  = ($headRes.output | Select-Object -First 1)
        $branchRes = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'rev-parse', '--abbrev-ref', 'HEAD')
        $git.branch = ($branchRes.output | Select-Object -First 1)

        $status = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'status', '--porcelain=v1', '-b', '--untracked-files=normal') -OutFile (Join-Path $gitDir 'status.txt')
        $changes = @($status.output | Where-Object { $_ -and ($_ -notlike '##*') })
        $git.dirty = ($changes.Count -gt 0)

        $remotes = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'remote', '-v') -OutFile (Join-Path $gitDir 'remotes.txt')
        $git.remotes = ($remotes.output -join '; ')
        [void](Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'for-each-ref', '--format=%(refname) %(objectname)') -OutFile (Join-Path $gitDir 'refs.txt'))
        [void](Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'stash', 'list') -OutFile (Join-Path $gitDir 'stash.txt'))
        [void](Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'count-objects', '-vH') -OutFile (Join-Path $gitDir 'objects.txt'))
        [void](Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'diff', '--binary', 'HEAD') -OutFile (Join-Path $runDir 'uncommitted.patch'))
        [void](Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'diff', '--cached', '--binary') -OutFile (Join-Path $runDir 'staged.patch'))

        Add-Finding 'git' 'repository' 'PASS' ('branch={0} head={1} dirty={2}' -f $git.branch, $git.head, $git.dirty)
    }
    else {
        Add-Finding 'git' 'repository' 'FAIL' 'not a git work tree; snapshot still valid, branch creation disabled'
    }

    # ---------------------------------------------------------------- G0.2 secret scan
    $script:Phase = 'secrets'
    Write-Host "`n== G0.2 redacted credential scan ==" -ForegroundColor Cyan
    $secretHits = New-Object System.Collections.ArrayList
    if ($git.isRepo) {
        $ls = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'ls-files')
        $patterns = @(
            @{ n = 'aws-key';        r = 'AKIA[0-9A-Z]{16}' },
            @{ n = 'github-token';   r = 'gh[pousr]_[A-Za-z0-9]{20,}' },
            @{ n = 'slack-token';    r = 'xox[baprs]-[A-Za-z0-9-]{10,}' },
            @{ n = 'provider-key';   r = 'sk-[A-Za-z0-9]{20,}' },
            @{ n = 'private-key';    r = '-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----' },
            @{ n = 'literal-bearer'; r = 'bearer [A-Za-z0-9._-]{20,}' }
        )
        foreach ($rel in $ls.output) {
            if (-not $rel) { continue }
            $full = Join-Path $ProjectRoot $rel
            if (-not (Test-Path -LiteralPath $full -PathType Leaf)) { continue }
            if ((Get-Item -LiteralPath $full).Length -gt 1MB) { continue }
            foreach ($p in $patterns) {
                $hit = Select-String -LiteralPath $full -Pattern $p.r -AllMatches -ErrorAction SilentlyContinue
                if ($hit) {
                    # Record file and pattern name only. Never print matched text.
                    [void]$secretHits.Add([pscustomobject]@{ file = $rel; pattern = $p.n; matches = @($hit).Count })
                }
            }
        }
    }
    if ($secretHits.Count -eq 0) {
        Add-Finding 'secrets' 'tracked-files' 'PASS' 'no credential patterns in tracked text files'
    }
    else {
        Add-Finding 'secrets' 'tracked-files' 'STOP' ('{0} file(s) matched; values redacted in secrets_report.json' -f $secretHits.Count)
        $secretHits | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'secrets_report.json') -Encoding UTF8
    }

    # ---------------------------------------------------------------- G0.3 media integrity
    $script:Phase = 'media'
    Write-Host "`n== G0.3 media inventory + SHA-256 ==" -ForegroundColor Cyan
    $mediaExtensions = @('.mp4', '.mov', '.avi', '.mkv', '.webm', '.m4v', '.wav', '.mp3')
    $dependencyDirs  = @('node_modules', '.venv', 'venv', '.git', '__pycache__', '.pytest_cache')

    $media = Get-FileManifest -Root $ProjectRoot -Extensions $mediaExtensions -ExcludeDirNames $dependencyDirs
    $media | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'media_manifest.json') -Encoding UTF8
    Add-Finding 'media' 'media-files' $(if ($media.Count -gt 0) { 'PASS' } else { 'FAIL' }) ('{0} media file(s) hashed' -f $media.Count)
    Add-Finding 'media' 'read-only' 'PASS' 'no media byte was modified by this script'

    if ($CompareMediaManifest) {
        $script:Phase = 'media-compare'
        Write-Host "`n== G0.3b media immutability comparison ==" -ForegroundColor Cyan
        if (-not (Test-Path -LiteralPath $CompareMediaManifest -PathType Leaf)) {
            Add-Finding 'media-compare' 'manifest' 'STOP' "manifest not found: $CompareMediaManifest"
        }
        else {
            $before = @(Get-Content -LiteralPath $CompareMediaManifest -Raw | ConvertFrom-Json)
            $beforeMap = @{}
            foreach ($b in $before) { $beforeMap[$b.relativePath] = $b.sha256 }

            $changed = New-Object System.Collections.ArrayList
            $added   = New-Object System.Collections.ArrayList
            $nowMap  = @{}
            foreach ($m in $media) {
                $nowMap[$m.relativePath] = $true
                if ($beforeMap.ContainsKey($m.relativePath)) {
                    if ($beforeMap[$m.relativePath] -ne $m.sha256) { [void]$changed.Add($m.relativePath) }
                }
                else { [void]$added.Add($m.relativePath) }
            }
            $removed = New-Object System.Collections.ArrayList
            foreach ($k in $beforeMap.Keys) {
                if (-not $nowMap.ContainsKey($k)) { [void]$removed.Add($k) }
            }
            [pscustomobject]@{ changed = $changed; added = $added; removed = $removed } |
                ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'media_diff.json') -Encoding UTF8

            if ($changed.Count -gt 0) {
                Add-Finding 'media-compare' 'originals-immutable' 'STOP' ('{0} previously hashed file(s) changed' -f $changed.Count)
            }
            else {
                Add-Finding 'media-compare' 'originals-immutable' 'PASS' ('0 changed, {0} added, {1} absent' -f $added.Count, $removed.Count)
            }
        }
    }

    # ---------------------------------------------------------------- G0.4 toolchain
    $script:Phase = 'versions'
    Write-Host "`n== G0.4 toolchain probe ==" -ForegroundColor Cyan
    $verDir = Join-Path $runDir 'versions'
    New-Item -ItemType Directory -Path $verDir -Force | Out-Null

    $pyv = Invoke-Tool -Exe $PythonExe -ArgList @('-c', 'import sys; print(sys.version)') -OutFile (Join-Path $verDir 'python.txt')
    Add-Finding 'versions' 'python' $(if ($pyv.exitCode -eq 0) { 'PASS' } else { 'FAIL' }) (($pyv.output | Select-Object -First 1) -join '')

    [void](Invoke-Tool -Exe $PythonExe -ArgList @('-m', 'pip', 'freeze') -OutFile (Join-Path $verDir 'pip-freeze.txt'))
    [void](Invoke-Tool -Exe 'ffmpeg'    -ArgList @('-version')      -OutFile (Join-Path $verDir 'ffmpeg.txt'))
    [void](Invoke-Tool -Exe 'node'      -ArgList @('-v')            -OutFile (Join-Path $verDir 'node.txt'))
    [void](Invoke-Tool -Exe 'npm'       -ArgList @('--version')     -OutFile (Join-Path $verDir 'npm.txt'))
    [void](Invoke-Tool -Exe $PythonExe  -ArgList @('-c', 'import importlib.metadata as m; print("Pose2Sim", m.version("Pose2Sim"))') -OutFile (Join-Path $verDir 'pose2sim.txt'))
    [void](Invoke-Tool -Exe $PythonExe  -ArgList @('-c', 'import opensim as o; print("OpenSim", o.GetVersion())') -OutFile (Join-Path $verDir 'opensim.txt'))
    [void](Invoke-Tool -Exe $PythonExe  -ArgList @('-c', 'import onnxruntime as r; print(r.__version__, r.get_available_providers())') -OutFile (Join-Path $verDir 'onnxruntime.txt'))

    # ---------------------------------------------------------------- G0.5 snapshot
    $script:Phase = 'snapshot'
    if (-not $SkipSnapshot) {
        Write-Host "`n== G0.5 rollback snapshot ==" -ForegroundColor Cyan
        $snapDir = Join-Path $runDir 'worktree'
        $excludeDirs = @('projects', 'node_modules', '.venv', 'venv', 'env', 'dist', 'build', '__pycache__', '.pytest_cache', '.mypy_cache', '.git', 'snapshots', 'backups', 'AppData')
        $excludeFiles = @('*.mp4', '*.mov', '*.avi', '*.mkv', '*.webm', '*.onnx', '*.pt', '*.pth', '*.ckpt', '*.sqlite', '*.db', '*.mot', '*.trc', '*.c3d', '*.blend', '*.zip')

        $rcArgs = @($ProjectRoot, $snapDir, '/E', '/R:1', '/W:1', '/NFL', '/NDL', '/NP', '/NJH', '/NJS', '/XD') + $excludeDirs + @('/XF') + $excludeFiles
        $rc = Invoke-Tool -Exe 'robocopy' -ArgList $rcArgs -OutFile (Join-Path $verDir 'robocopy.txt')
        if ($rc.exitCode -lt 8) {
            Add-Finding 'snapshot' 'worktree-copy' 'PASS' "code snapshot at $snapDir"
            $snapManifest = Get-FileManifest -Root $snapDir
            $snapManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $runDir 'snapshot_manifest.json') -Encoding UTF8
            $mismatch = 0
            foreach ($s in $snapManifest) {
                $source = Join-Path $ProjectRoot $s.relativePath
                if (Test-Path -LiteralPath $source -PathType Leaf) {
                    if ((Get-Sha256 -Path $source) -ne $s.sha256) { $mismatch++ }
                }
            }
            Add-Finding 'snapshot' 'hash-verify' $(if ($mismatch -eq 0) { 'PASS' } else { 'FAIL' }) ('{0} file(s) compared, {1} mismatch(es)' -f $snapManifest.Count, $mismatch)
        }
        else {
            Add-Finding 'snapshot' 'worktree-copy' 'FAIL' ('robocopy exit {0} (>=8 is an error)' -f $rc.exitCode)
        }

        if ($git.isRepo) {
            $bundlePath = Join-Path $runDir 'history.bundle'
            $bundle = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'bundle', 'create', $bundlePath, '--all') -OutFile (Join-Path $verDir 'git-bundle.txt')
            Add-Finding 'snapshot' 'history-bundle' $(if ($bundle.exitCode -eq 0) { 'PASS' } else { 'FAIL' }) $(if ($bundle.exitCode -eq 0) { $bundlePath } else { 'bundle failed; patch files alone are incomplete rollback' })
        }
    }
    else {
        Add-Finding 'snapshot' 'worktree-copy' 'SKIP' 'snapshot skipped by switch'
    }

    # ---------------------------------------------------------------- G0.6 baselines
    $script:Phase = 'baseline'
    if (-not $SkipTests) {
        Write-Host "`n== G0.6 baseline capture ==" -ForegroundColor Cyan
        $baseDir = Join-Path $runDir 'baseline'
        New-Item -ItemType Directory -Path $baseDir -Force | Out-Null

        $pyArgs = @($PythonTestArgs.Split(' ', [System.StringSplitOptions]::RemoveEmptyEntries))
        $pyArgs += @('--junitxml', (Join-Path $baseDir 'pytest.xml'))
        $pyRun = Invoke-Tool -Exe $PythonExe -ArgList $pyArgs -WorkDir $ProjectRoot -OutFile (Join-Path $baseDir 'pytest.log')
        Add-Finding 'baseline' 'python-tests' $(if ($pyRun.exitCode -eq 0) { 'PASS' } else { 'FAIL' }) ('exit={0}' -f $pyRun.exitCode)

        if ($JsTestCommand) {
            $jsRun = Invoke-Tool -Exe 'cmd.exe' -ArgList @('/c', $JsTestCommand) -WorkDir $ProjectRoot -OutFile (Join-Path $baseDir 'js-tests.log')
            Add-Finding 'baseline' 'js-tests' $(if ($jsRun.exitCode -eq 0) { 'PASS' } else { 'FAIL' }) ('exit={0}' -f $jsRun.exitCode)
        }
        else { Add-Finding 'baseline' 'js-tests' 'SKIP' 'pass -JsTestCommand to include' }

        if ($BuildCommand) {
            $bRun = Invoke-Tool -Exe 'cmd.exe' -ArgList @('/c', $BuildCommand) -WorkDir $ProjectRoot -OutFile (Join-Path $baseDir 'build.log')
            Add-Finding 'baseline' 'build' $(if ($bRun.exitCode -eq 0) { 'PASS' } else { 'FAIL' }) ('exit={0}' -f $bRun.exitCode)
        }
    }
    else { Add-Finding 'baseline' 'tests' 'SKIP' 'tests skipped by switch' }

    # ---------------------------------------------------------------- G0.7 branch
    $script:Phase = 'branch'
    if ($CreateBranch) {
        Write-Host "`n== G0.7 feature branch ==" -ForegroundColor Cyan
        if (-not $git.isRepo) {
            Add-Finding 'branch' 'create' 'FAIL' 'no git work tree'
        }
        else {
            $exists = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'rev-parse', '--verify', '--quiet', ('refs/heads/' + $BranchName))
            if ($exists.exitCode -eq 0) {
                Add-Finding 'branch' 'create' 'FAIL' "branch already exists: $BranchName (no reset performed)"
            }
            else {
                $created = Invoke-Tool -Exe 'git' -ArgList @('-C', $ProjectRoot, 'switch', '-c', $BranchName) -OutFile (Join-Path $gitDir 'branch-create.txt')
                Add-Finding 'branch' 'create' $(if ($created.exitCode -eq 0) { 'PASS' } else { 'FAIL' }) $(if ($created.exitCode -eq 0) { "on $BranchName" } else { 'switch failed; worktree unchanged' })
            }
        }
    }
    else { Add-Finding 'branch' 'create' 'SKIP' 'review the report first, then re-run with -CreateBranch' }
}
catch {
    Add-Finding $script:Phase 'unhandled-error' 'FAIL' ($_.Exception.Message)
}
finally {
    $stops = @($script:Findings | Where-Object { $_.status -eq 'STOP' })
    $fails = @($script:Findings | Where-Object { $_.status -eq 'FAIL' })

    if     ($stops.Count -gt 0) { $verdict = 'STOP' }
    elseif ($fails.Count -gt 0) { $verdict = 'G0_PASSED_WITH_WARNINGS' }
    else                        { $verdict = 'G0_PASSED' }

    if ($runDir) {
        $report = [pscustomobject]@{
            generatedUtc = (Get-Date).ToUniversalTime().ToString('o')
            host         = $env:COMPUTERNAME
            script       = 'tools/g0_preflight.ps1'
            projectRoot  = $ProjectRoot
            runDir       = $runDir
            verdict      = $verdict
            stopCount    = $stops.Count
            failCount    = $fails.Count
            git          = $git
            findings     = $script:Findings
        }
        $reportPath = Join-Path $runDir 'g0-report.json'
        try {
            $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
        }
        catch {
            $reportPath = Join-Path $env:TEMP ('g0-report-' + $stamp + '.json')
            $report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $reportPath -Encoding UTF8
        }

        $md = New-Object System.Text.StringBuilder
        [void]$md.AppendLine('# G0 audit - ' + $stamp)
        [void]$md.AppendLine('')
        [void]$md.AppendLine('Verdict: **' + $verdict + '** | STOP=' + $stops.Count + ' FAIL=' + $fails.Count + ' | host `' + $env:COMPUTERNAME + '`')
        [void]$md.AppendLine('')
        [void]$md.AppendLine('| Phase | Check | Status | Detail |')
        [void]$md.AppendLine('|---|---|---|---|')
        foreach ($f in $script:Findings) {
            $detail = ([string]$f.detail) -replace '\|', '\|'
            [void]$md.AppendLine('| ' + $f.phase + ' | ' + $f.check + ' | ' + $f.status + ' | ' + $detail + ' |')
        }
        $mdPath = Join-Path $runDir 'G0_REPORT.md'
        Set-Content -LiteralPath $mdPath -Value $md.ToString() -Encoding UTF8

        if ($WriteDocsIntoProject) {
            $docsDir = Join-Path $ProjectRoot 'docs'
            if (-not (Test-Path -LiteralPath $docsDir)) { New-Item -ItemType Directory -Path $docsDir | Out-Null }
            $target = Join-Path $docsDir 'G0_REPORT.md'
            if (Test-Path -LiteralPath $target) {
                Write-Host '  docs/G0_REPORT.md exists - not overwritten' -ForegroundColor Yellow
            }
            else {
                Copy-Item -LiteralPath $mdPath -Destination $target
                Write-Host "  wrote $target" -ForegroundColor Green
            }
        }

        Write-Host ''
        Write-Host ('=== G0 VERDICT: ' + $verdict + ' ===') -ForegroundColor $(if ($verdict -eq 'STOP') { 'Red' } else { 'Green' })
        Write-Host ('Report : ' + $reportPath)
        Write-Host ('Summary: ' + $mdPath)
        Write-Host ''
        Write-Host 'Next: return g0-report.json to the executing agent. G1 does not start until this is clean.'
    }

    if ($stops.Count -gt 0) { exit 3 }
    if ($fails.Count -gt 0) { exit 2 }
    exit 0
}
