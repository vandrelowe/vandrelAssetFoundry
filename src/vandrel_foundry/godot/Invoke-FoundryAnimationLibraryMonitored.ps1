#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$GodotExe,
    [Parameter(Mandatory = $true)][string]$SandboxPath,
    [Parameter(Mandatory = $true)][ValidateRange(1, 900)][int]$TimeoutSeconds,
    [Parameter(Mandatory = $true)][ValidateRange(1, 50000000)][int]$MaximumOutputBytes
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-GodotProcesses {
    return @(
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -match '(?i)^Godot' } |
            ForEach-Object { [ordered]@{ pid = $_.Id; process_name = $_.ProcessName; title = $_.MainWindowTitle } }
    )
}

function Get-GodotApplicationErrorWindows {
    return @(
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object {
                -not [string]::IsNullOrWhiteSpace($_.MainWindowTitle) -and
                $_.MainWindowTitle -match '(?i)^Godot.*\s*-\s*Application Error'
            } |
            ForEach-Object {
                [ordered]@{
                    pid = $_.Id
                    process_name = $_.ProcessName
                    title = $_.MainWindowTitle
                    observed_utc = [DateTime]::UtcNow.ToString('O')
                }
            }
    )
}

function Get-FileLength([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return 0 }
    return (Get-Item -LiteralPath $Path).Length
}

if (-not (Test-Path -LiteralPath $GodotExe -PathType Leaf)) { throw 'Godot console executable does not exist.' }
$resolvedGodot = (Resolve-Path -LiteralPath $GodotExe).Path
if ([IO.Path]::GetFileNameWithoutExtension($resolvedGodot) -notmatch 'console$') { throw 'GodotExe must name the console executable.' }
if (-not (Test-Path -LiteralPath $SandboxPath -PathType Container)) { throw 'Animation sandbox does not exist.' }
$resolvedSandbox = (Resolve-Path -LiteralPath $SandboxPath).Path
$outputRoot = Join-Path $resolvedSandbox 'output'
$monitorPath = Join-Path $outputRoot 'animation-library-godot-monitor.json'
if (Test-Path -LiteralPath $monitorPath) { throw 'Animation monitor output already exists.' }
$preexisting = @(Get-GodotProcesses)
if ($preexisting.Count -ne 0) { throw 'Animation processing requires process-zero before launch.' }

$runStartedUtc = [DateTime]::UtcNow
$eventStart = $runStartedUtc.AddSeconds(-5)
$observedWindows = [System.Collections.Generic.List[object]]::new()
$phaseResults = [System.Collections.Generic.List[object]]::new()
$timedOut = $false
$outputLimited = $false
$cleanupFailed = $false
$cleanupIssue = ''
$phaseSpecs = @(
    [ordered]@{ name = 'initial_import'; arguments = @('--headless', '--path', $resolvedSandbox, '--import', '--quit-after', '600') },
    [ordered]@{ name = 'configure_imports'; arguments = @('--headless', '--path', $resolvedSandbox, '--script', 'res://configure_animation_library_imports.gd', '--quit-after', '600') },
    [ordered]@{ name = 'retargeted_import'; arguments = @('--headless', '--path', $resolvedSandbox, '--import', '--quit-after', '600') },
    [ordered]@{ name = 'finalize_probe'; arguments = @('--headless', '--path', $resolvedSandbox, '--script', 'res://finalize_animation_library.gd', '--quit-after', '600') },
    [ordered]@{ name = 'isolated_validate'; arguments = @('--headless', '--path', $resolvedSandbox, '--script', 'res://validate_isolated_animation_library.gd', '--quit-after', '600') }
)
$activeProcess = $null
$passed = $false

try {
    foreach ($phase in $phaseSpecs) {
        if ($phase.name -eq 'isolated_validate') {
            foreach ($relativeTarget in @('sources', '.godot')) {
                $target = [IO.Path]::GetFullPath((Join-Path $resolvedSandbox $relativeTarget))
                $requiredPrefix = $resolvedSandbox.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
                if (-not $target.StartsWith($requiredPrefix, [StringComparison]::OrdinalIgnoreCase)) {
                    throw "Refusing isolated-validation cleanup outside sandbox: $target"
                }
                if (Test-Path -LiteralPath $target) {
                    Remove-Item -LiteralPath $target -Recurse -Force
                }
            }
        }
        $stdoutPath = Join-Path $resolvedSandbox ('.foundry-' + $phase.name + '-stdout.log')
        $stderrPath = Join-Path $resolvedSandbox ('.foundry-' + $phase.name + '-stderr.log')
        $godotLog = Join-Path $resolvedSandbox ('.foundry-' + $phase.name + '-godot.log')
        foreach ($path in @($stdoutPath, $stderrPath, $godotLog)) {
            if (Test-Path -LiteralPath $path) { throw "Monitored phase output already exists: $path" }
        }
        $arguments = @($phase.arguments) + @('--log-file', $godotLog)
        $process = $null
        $phaseStarted = [DateTime]::UtcNow
        $phaseExit = $null
        try {
            $process = Start-Process `
                -Environment @{ DOTNET_ROLL_FORWARD = 'LatestMajor' } `
                -FilePath $resolvedGodot `
                -ArgumentList $arguments `
                -WorkingDirectory $resolvedSandbox `
                -RedirectStandardOutput $stdoutPath `
                -RedirectStandardError $stderrPath `
                -WindowStyle Hidden `
                -PassThru
            $activeProcess = $process
            $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
            $applicationErrorObserved = $false
            while (-not $process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
                foreach ($window in @(Get-GodotApplicationErrorWindows)) {
                    $observedWindows.Add($window)
                    $applicationErrorObserved = $true
                }
                $observedBytes = (Get-FileLength $stdoutPath) + (Get-FileLength $stderrPath) + (Get-FileLength $godotLog)
                if ($observedBytes -gt $MaximumOutputBytes) { $outputLimited = $true; break }
                if ($applicationErrorObserved) { break }
                Start-Sleep -Milliseconds 250
            }
            if (-not $process.HasExited -and -not $applicationErrorObserved -and -not $outputLimited) { $timedOut = $true }
            if (-not $process.HasExited -and ($timedOut -or $applicationErrorObserved -or $outputLimited)) {
                $process.Kill($true)
                if (-not $process.WaitForExit(10000)) { throw 'Run-owned Godot process tree did not exit.' }
            }
            if ($process.HasExited) { $phaseExit = $process.ExitCode }
        }
        catch {
            $cleanupFailed = $true
            $cleanupIssue = $_.Exception.Message
            if ($null -ne $process -and -not $process.HasExited) {
                try { $process.Kill($true); [void]$process.WaitForExit(10000) } catch { }
            }
        }
        finally {
            $activeProcess = $null
        }
        $phaseResults.Add([ordered]@{
            phase = $phase.name
            started_utc = $phaseStarted.ToString('O')
            ended_utc = [DateTime]::UtcNow.ToString('O')
            exit_code = $phaseExit
            stdout_path = [IO.Path]::GetFileName($stdoutPath)
            stderr_path = [IO.Path]::GetFileName($stderrPath)
            godot_log_path = [IO.Path]::GetFileName($godotLog)
        })
        if ($phaseExit -ne 0 -or $timedOut -or $outputLimited -or $cleanupFailed -or $observedWindows.Count -gt 0) { break }
    }
}
catch {
    $cleanupFailed = $true
    $cleanupIssue = $_.Exception.Message
    if ($null -ne $activeProcess -and -not $activeProcess.HasExited) {
        try {
            $activeProcess.Kill($true)
            if (-not $activeProcess.WaitForExit(10000)) {
                $cleanupIssue = "$cleanupIssue; run-owned process tree did not exit"
            }
        }
        catch {
            $cleanupIssue = "$cleanupIssue; cleanup failed: $($_.Exception.Message)"
        }
    }
}
finally {
    $postExitDeadline = [DateTime]::UtcNow.AddSeconds(5)
    while ([DateTime]::UtcNow -lt $postExitDeadline) {
        foreach ($window in @(Get-GodotApplicationErrorWindows)) { $observedWindows.Add($window) }
        Start-Sleep -Milliseconds 250
    }
    $runEndedUtc = [DateTime]::UtcNow
    $eventEnd = $runEndedUtc.AddMinutes(2)
    $events = @(
    Get-WinEvent -FilterHashtable @{
        LogName = 'Application'; StartTime = $eventStart.ToLocalTime(); EndTime = $eventEnd.ToLocalTime()
    } -ErrorAction SilentlyContinue |
        Where-Object {
            $_.ProviderName -in @('Application Error', 'Windows Error Reporting', '.NET Runtime') -and
            $_.Message -match '(?i)Godot[^\s]*\.exe|coreclr\.dll'
        } |
        ForEach-Object {
            [ordered]@{
                time_utc = $_.TimeCreated.ToUniversalTime().ToString('O')
                provider = $_.ProviderName
                event_id = $_.Id
                level = $_.LevelDisplayName
                message = $_.Message
            }
        }
    )
    $evidenceRoots = @(
    (Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportArchive'),
    (Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportQueue'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER'),
    (Join-Path $env:LOCALAPPDATA 'CrashDumps')
    )
    $werPaths = [System.Collections.Generic.List[object]]::new()
    foreach ($root in $evidenceRoots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        foreach ($item in @(Get-ChildItem -LiteralPath $root -Recurse -ErrorAction SilentlyContinue)) {
            if ($item.LastWriteTimeUtc -lt $eventStart -or $item.LastWriteTimeUtc -gt $eventEnd) { continue }
            if ($item.FullName -notmatch '(?i)Godot|Report\.wer$|\.dmp$') { continue }
            $werPaths.Add([ordered]@{
                path = $item.FullName
                is_directory = $item.PSIsContainer
                bytes = if ($item.PSIsContainer) { 0 } else { $item.Length }
                modified_utc = $item.LastWriteTimeUtc.ToString('O')
            })
        }
    }
    $remaining = @(Get-GodotProcesses)
    $hasCrashEvidence = $observedWindows.Count -gt 0 -or $events.Count -gt 0 -or $werPaths.Count -gt 0
    $allPhases = @($phaseResults).Count -eq $phaseSpecs.Count -and @($phaseResults | Where-Object { $_.exit_code -ne 0 }).Count -eq 0
    $passed = $allPhases -and -not $timedOut -and -not $outputLimited -and -not $cleanupFailed -and -not $hasCrashEvidence -and $remaining.Count -eq 0
    $record = [ordered]@{
    schema_version = 'vandrel_foundry_animation_godot_monitor/1.0'
    policy = 'vandrel_monitored_godot_animation_library_corridor_2026-08-21'
    run_started_utc = $runStartedUtc.ToString('O')
    run_ended_utc = $runEndedUtc.ToString('O')
    console_executable_name = [IO.Path]::GetFileName($resolvedGodot)
    console_file_version = [Diagnostics.FileVersionInfo]::GetVersionInfo($resolvedGodot).FileVersion
    godot_console_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedGodot).Hash.ToLowerInvariant()
    supervisor_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath).Hash.ToLowerInvariant()
    process_zero_preflight = $true
    child_environment = @{ DOTNET_ROLL_FORWARD = 'LatestMajor' }
    phases = @($phaseSpecs | ForEach-Object { $_.name })
    phase_results = @($phaseResults)
    outer_timeout_seconds_per_phase = $TimeoutSeconds
    internal_iteration_bomb = 600
    post_exit_poll_seconds = 5
    timed_out = $timedOut
    output_limited = $outputLimited
    cleanup_failed = $cleanupFailed
    cleanup_issue = $cleanupIssue
    application_error_windows = @($observedWindows)
    application_events = $events
    wer_and_dump_paths = @($werPaths)
    final_godot_processes = $remaining
    has_crash_evidence = $hasCrashEvidence
    passed = $passed
    }
    $json = $record | ConvertTo-Json -Depth 10
    [IO.File]::WriteAllText($monitorPath, $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}
if (-not $passed) { exit 1 }
exit 0
