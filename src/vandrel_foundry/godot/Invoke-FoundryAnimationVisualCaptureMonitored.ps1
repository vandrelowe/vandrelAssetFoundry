#!/usr/bin/env pwsh

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$GodotExe,
    [Parameter(Mandatory = $true)][string]$SandboxPath,
    [Parameter(Mandatory = $true)][ValidateRange(1, 900)][int]$TimeoutSeconds,
    [Parameter(Mandatory = $true)][ValidateRange(1, 50000000)][int]$MaximumOutputBytes,
    [Parameter(Mandatory = $true)][string]$RuntimeRequestSha256,
    [Parameter(Mandatory = $true)][string]$CaptureScriptSha256,
    [Parameter(Mandatory = $true)][string]$CameraConfigSha256
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-GodotProcesses {
    return @(
        Get-Process -ErrorAction SilentlyContinue |
            Where-Object { $_.ProcessName -match '(?i)^Godot' } |
            ForEach-Object {
                [ordered]@{
                    pid = $_.Id
                    process_name = $_.ProcessName
                    title = $_.MainWindowTitle
                }
            }
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

function Add-FailureDetail([string]$Current, [string]$Detail) {
    if ([string]::IsNullOrWhiteSpace($Current)) { return $Detail }
    return "$Current; $Detail"
}

$expectedCameraHash = '6852a2bfd195cf5f1f885d166ec92977958668cb6a58ed868c91708fa2923eaf'
$runStartedUtc = [DateTime]::UtcNow
$resolvedSandbox = $null
$resolvedGodot = $null
$monitorPath = $null
$consoleName = $null
$consoleVersion = $null
$godotSha256 = $null
$supervisorSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath).Hash.ToLowerInvariant()
$preflights = [ordered]@{
    sandbox = $false
    godot_console = $false
    runtime_request = $false
    capture_script = $false
    camera_config = $false
    initial_process_zero = $false
}
$phaseSpecs = @(
    [ordered]@{ name = 'import'; arguments = @('--headless', '--import', '--quit-after', '600') },
    [ordered]@{
        name = 'capture'
        arguments = @('--headless', '--script', 'res://capture_animation_visual_matrix.gd', '--quit-after', '600')
    }
)
$phaseResults = [System.Collections.Generic.List[object]]::new()
$observedWindows = [System.Collections.Generic.List[object]]::new()
$timedOut = $false
$outputLimited = $false
$cleanupFailed = $false
$cleanupIssue = ''
$failureStage = $null
$failureMessage = $null
$activeProcess = $null
$godotStarted = $false
$passed = $false

try {
    if (-not (Test-Path -LiteralPath $SandboxPath -PathType Container)) {
        throw 'Animation visual-capture sandbox does not exist.'
    }
    $resolvedSandbox = (Resolve-Path -LiteralPath $SandboxPath).Path
    $outputRoot = Join-Path $resolvedSandbox 'output'
    if (-not (Test-Path -LiteralPath $outputRoot -PathType Container)) {
        throw 'Animation visual-capture output directory does not exist.'
    }
    $monitorPath = Join-Path $outputRoot 'animation-visual-godot-monitor.json'
    if (Test-Path -LiteralPath $monitorPath) {
        throw 'Animation visual monitor output already exists.'
    }
    $preflights.sandbox = $true

    if ($CameraConfigSha256 -notmatch '^[a-f0-9]{64}$' -or $CameraConfigSha256 -ne $expectedCameraHash) {
        throw 'Animation visual camera configuration hash is not canonical.'
    }
    $preflights.camera_config = $true

    $runtimePath = Join-Path $resolvedSandbox 'animation-visual-runtime.json'
    if (
        $RuntimeRequestSha256 -notmatch '^[a-f0-9]{64}$' -or
        -not (Test-Path -LiteralPath $runtimePath -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $runtimePath).Hash.ToLowerInvariant() -ne $RuntimeRequestSha256
    ) {
        throw 'Animation visual runtime request is missing or hash-mismatched.'
    }
    $preflights.runtime_request = $true

    $scriptPath = Join-Path $resolvedSandbox 'capture_animation_visual_matrix.gd'
    if (
        $CaptureScriptSha256 -notmatch '^[a-f0-9]{64}$' -or
        -not (Test-Path -LiteralPath $scriptPath -PathType Leaf) -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $scriptPath).Hash.ToLowerInvariant() -ne $CaptureScriptSha256
    ) {
        throw 'Animation visual capture script is missing or hash-mismatched.'
    }
    $preflights.capture_script = $true

    if (-not (Test-Path -LiteralPath $GodotExe -PathType Leaf)) {
        throw 'Godot console executable does not exist.'
    }
    $resolvedGodot = (Resolve-Path -LiteralPath $GodotExe).Path
    if ([IO.Path]::GetFileNameWithoutExtension($resolvedGodot) -notmatch 'console$') {
        throw 'GodotExe must name the console executable.'
    }
    $consoleName = [IO.Path]::GetFileName($resolvedGodot)
    $consoleVersion = [Diagnostics.FileVersionInfo]::GetVersionInfo($resolvedGodot).FileVersion
    if ([string]::IsNullOrWhiteSpace($consoleVersion)) {
        throw 'Godot console executable has no file version.'
    }
    $godotSha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $resolvedGodot).Hash.ToLowerInvariant()
    $preflights.godot_console = $true

    if (@(Get-GodotProcesses).Count -ne 0) {
        throw 'Animation visual capture requires process-zero before launch.'
    }
    $preflights.initial_process_zero = $true

    foreach ($phase in $phaseSpecs) {
        if (@(Get-GodotProcesses).Count -ne 0) {
            throw "Animation visual capture phase $($phase.name) requires process-zero."
        }
        $stdoutPath = Join-Path $resolvedSandbox ('.foundry-' + $phase.name + '-stdout.log')
        $stderrPath = Join-Path $resolvedSandbox ('.foundry-' + $phase.name + '-stderr.log')
        $godotLog = Join-Path $resolvedSandbox ('.foundry-' + $phase.name + '-godot.log')
        foreach ($path in @($stdoutPath, $stderrPath, $godotLog)) {
            if (Test-Path -LiteralPath $path) {
                throw "Monitored visual-capture phase output already exists: $path"
            }
        }
        $arguments = @($phase.arguments) + @('--path', $resolvedSandbox, '--log-file', $godotLog)
        $process = $null
        $phaseStarted = [DateTime]::UtcNow
        $phaseExit = $null
        $phaseProcessZero = $true
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
            $godotStarted = $true
            $activeProcess = $process
            $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
            $applicationErrorObserved = $false
            while (-not $process.HasExited -and [DateTime]::UtcNow -lt $deadline) {
                foreach ($window in @(Get-GodotApplicationErrorWindows)) {
                    $observedWindows.Add($window)
                    $applicationErrorObserved = $true
                }
                $observedBytes =
                    (Get-FileLength $stdoutPath) +
                    (Get-FileLength $stderrPath) +
                    (Get-FileLength $godotLog)
                if ($observedBytes -gt $MaximumOutputBytes) {
                    $outputLimited = $true
                    break
                }
                if ($applicationErrorObserved) { break }
                Start-Sleep -Milliseconds 250
            }
            if (-not $process.HasExited -and -not $applicationErrorObserved -and -not $outputLimited) {
                $timedOut = $true
            }
            if (-not $process.HasExited -and ($timedOut -or $applicationErrorObserved -or $outputLimited)) {
                $process.Kill($true)
                if (-not $process.WaitForExit(10000)) {
                    throw 'Run-owned Godot process tree did not exit.'
                }
            }
            if ($process.HasExited) { $phaseExit = $process.ExitCode }
        }
        catch {
            $failureStage = "phase:$($phase.name)"
            $failureMessage = $_.Exception.Message
            if ($null -ne $process -and -not $process.HasExited) {
                try {
                    $process.Kill($true)
                    if (-not $process.WaitForExit(10000)) {
                        throw 'Run-owned process tree did not exit during phase cleanup.'
                    }
                }
                catch {
                    $cleanupFailed = $true
                    $cleanupIssue = $_.Exception.Message
                }
            }
        }
        finally {
            $activeProcess = $null
        }
        $phasePostExitDeadline = [DateTime]::UtcNow.AddSeconds(5)
        while ([DateTime]::UtcNow -lt $phasePostExitDeadline) {
            foreach ($window in @(Get-GodotApplicationErrorWindows)) {
                $observedWindows.Add($window)
            }
            Start-Sleep -Milliseconds 250
        }
        $phaseResults.Add([ordered]@{
            phase = $phase.name
            process_zero_preflight = $phaseProcessZero
            post_exit_poll_seconds = 5
            started_utc = $phaseStarted.ToString('O')
            ended_utc = [DateTime]::UtcNow.ToString('O')
            exit_code = $phaseExit
            stdout_path = [IO.Path]::GetFileName($stdoutPath)
            stderr_path = [IO.Path]::GetFileName($stderrPath)
            godot_log_path = [IO.Path]::GetFileName($godotLog)
        })
        if (
            $phaseExit -ne 0 -or $timedOut -or $outputLimited -or
            $cleanupFailed -or $observedWindows.Count -gt 0
        ) {
            if ($null -eq $failureStage) { $failureStage = "phase:$($phase.name)" }
            if ($null -eq $failureMessage) {
                $failureMessage = "Godot phase exited with code $phaseExit."
            }
            break
        }
    }
}
catch {
    if ($null -eq $failureStage) { $failureStage = 'preflight_or_supervision' }
    $failureMessage = Add-FailureDetail $failureMessage $_.Exception.Message
}
finally {
    if ($null -ne $activeProcess -and -not $activeProcess.HasExited) {
        try {
            $activeProcess.Kill($true)
            if (-not $activeProcess.WaitForExit(10000)) {
                throw 'Run-owned process tree did not exit during final cleanup.'
            }
        }
        catch {
            $cleanupFailed = $true
            $cleanupIssue = Add-FailureDetail $cleanupIssue $_.Exception.Message
        }
    }
    $postExitPollSeconds = if ($godotStarted) { 5 } else { 0 }
    if ($godotStarted) {
        $postExitDeadline = [DateTime]::UtcNow.AddSeconds(5)
        while ([DateTime]::UtcNow -lt $postExitDeadline) {
            foreach ($window in @(Get-GodotApplicationErrorWindows)) {
                $observedWindows.Add($window)
            }
            Start-Sleep -Milliseconds 250
        }
    }
    $runEndedUtc = [DateTime]::UtcNow
    $events = @()
    $werPaths = [System.Collections.Generic.List[object]]::new()
    if ($godotStarted) {
        $eventStart = $runStartedUtc.AddSeconds(-5)
        $eventEnd = $runEndedUtc.AddMinutes(2)
        try {
            $events = @(
                Get-WinEvent -FilterHashtable @{
                    LogName = 'Application'
                    StartTime = $eventStart.ToLocalTime()
                    EndTime = $eventEnd.ToLocalTime()
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
        }
        catch {
            $failureMessage = Add-FailureDetail $failureMessage "event query failed: $($_.Exception.Message)"
        }
        $evidenceRoots = [System.Collections.Generic.List[string]]::new()
        if (-not [string]::IsNullOrWhiteSpace($env:ProgramData)) {
            $evidenceRoots.Add((Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportArchive'))
            $evidenceRoots.Add((Join-Path $env:ProgramData 'Microsoft\Windows\WER\ReportQueue'))
        }
        if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
            $evidenceRoots.Add((Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\WER'))
            $evidenceRoots.Add((Join-Path $env:LOCALAPPDATA 'CrashDumps'))
        }
        foreach ($root in $evidenceRoots) {
            if (-not (Test-Path -LiteralPath $root)) { continue }
            foreach ($item in @(Get-ChildItem -LiteralPath $root -Recurse -ErrorAction SilentlyContinue)) {
                if ($item.LastWriteTimeUtc -lt $eventStart -or $item.LastWriteTimeUtc -gt $eventEnd) {
                    continue
                }
                if ($item.FullName -notmatch '(?i)Godot|Report\.wer$|\.dmp$') { continue }
                $werPaths.Add([ordered]@{
                    path = $item.FullName
                    is_directory = $item.PSIsContainer
                    bytes = if ($item.PSIsContainer) { 0 } else { $item.Length }
                    modified_utc = $item.LastWriteTimeUtc.ToString('O')
                })
            }
        }
    }
    $remaining = @(Get-GodotProcesses)
    $hasCrashEvidence =
        $observedWindows.Count -gt 0 -or $events.Count -gt 0 -or $werPaths.Count -gt 0
    $allPhases =
        @($phaseResults).Count -eq $phaseSpecs.Count -and
        @($phaseResults | Where-Object { $_.exit_code -ne 0 }).Count -eq 0
    $passed =
        @($preflights.Values | Where-Object { -not $_ }).Count -eq 0 -and
        $allPhases -and -not $timedOut -and -not $outputLimited -and
        -not $cleanupFailed -and -not $hasCrashEvidence -and $remaining.Count -eq 0
    if (-not $passed -and $null -eq $failureStage) { $failureStage = 'evidence_or_inventory' }
    if (-not $passed -and $null -eq $failureMessage) {
        $failureMessage = 'Monitored capture policy did not pass.'
    }
    if ($null -ne $monitorPath -and -not (Test-Path -LiteralPath $monitorPath)) {
        $record = [ordered]@{
            schema_version = 'vandrel_foundry_animation_visual_capture_monitor/1.0'
            policy = 'vandrel_monitored_godot_animation_visual_capture_corridor_2026-08-21'
            run_started_utc = $runStartedUtc.ToString('O')
            run_ended_utc = $runEndedUtc.ToString('O')
            console_executable_name = $consoleName
            console_file_version = $consoleVersion
            godot_console_sha256 = $godotSha256
            supervisor_sha256 = $supervisorSha256
            runtime_request_sha256 = $RuntimeRequestSha256
            capture_script_sha256 = $CaptureScriptSha256
            camera_config_sha256 = $CameraConfigSha256
            preflights = $preflights
            process_zero_preflight = $preflights.initial_process_zero
            child_environment = @{ DOTNET_ROLL_FORWARD = 'LatestMajor' }
            phases = @($phaseSpecs | ForEach-Object { $_.name })
            phase_results = @($phaseResults)
            outer_timeout_seconds_per_phase = $TimeoutSeconds
            internal_iteration_bomb = 600
            post_exit_poll_seconds = $postExitPollSeconds
            timed_out = $timedOut
            output_limited = $outputLimited
            cleanup_failed = $cleanupFailed
            cleanup_issue = $cleanupIssue
            failure_stage = $failureStage
            failure_message = $failureMessage
            application_error_windows = @($observedWindows)
            application_events = $events
            wer_and_dump_paths = @($werPaths)
            final_godot_processes = $remaining
            has_crash_evidence = $hasCrashEvidence
            passed = $passed
        }
        [IO.File]::WriteAllText(
            $monitorPath,
            ($record | ConvertTo-Json -Depth 10) + [Environment]::NewLine,
            [Text.UTF8Encoding]::new($false)
        )
    }
}

if (-not $passed) { exit 1 }
exit 0
