#!/usr/bin/env pwsh
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$GodotExe,
    [Parameter(Mandatory=$true)][string]$SandboxPath,
    [Parameter(Mandatory=$true)][ValidateRange(1,900)][int]$TimeoutSeconds,
    [Parameter(Mandatory=$true)][ValidateRange(1,50000000)][int]$MaximumOutputBytes,
    [Parameter(Mandatory=$true)][string]$RuntimeGuardPath,
    [Parameter(Mandatory=$true)][string]$CrashEvidenceScriptPath
)
$ErrorActionPreference='Stop'; Set-StrictMode -Version Latest
$started=[DateTime]::UtcNow; $ended=$started
$sandbox=[IO.Path]::GetFullPath($SandboxPath); $output=Join-Path $sandbox 'output'; $monitor=Join-Path $output 'clean-body-godot-monitor.json'
$godot=$null; $windows=[Collections.Generic.List[object]]::new(); $results=[Collections.Generic.List[object]]::new(); $failed=''; $timedOut=$false; $limited=$false; $cleanupFailed=$false; $processZero=$false; $authorityLoaded=$false; $childEnvironment=@{}; $phases=@()
try {
if (-not (Test-Path -LiteralPath $RuntimeGuardPath -PathType Leaf) -or -not (Test-Path -LiteralPath $CrashEvidenceScriptPath -PathType Leaf)) { throw 'Canonical monitored Godot authority is unavailable.' }
. (Resolve-Path -LiteralPath $RuntimeGuardPath).Path
. (Resolve-Path -LiteralPath $CrashEvidenceScriptPath).Path
foreach($requiredFunction in @('Get-VandrelGodotChildEnvironment','Test-VandrelGodotProcessName','Test-VandrelGodotConsoleExecutableName','Get-VandrelGodotApplicationErrorWindows','Wait-VandrelGodotProcessWithCrashEvidence','Write-VandrelGodotCrashEvidence')) {if(-not(Get-Command -Name $requiredFunction -CommandType Function -ErrorAction SilentlyContinue)){throw "Canonical monitored function is unavailable: $requiredFunction"}}
$authorityLoaded=$true
function Get-GodotProcesses { @((Get-Process -ErrorAction SilentlyContinue | Where-Object {Test-VandrelGodotProcessName -ProcessName $_.ProcessName} | ForEach-Object {[ordered]@{pid=$_.Id;process_name=$_.ProcessName;title=$_.MainWindowTitle}})) }
function Get-ErrorWindows { @(Get-VandrelGodotApplicationErrorWindows) }
function Get-Length([string]$Path) { if (Test-Path -LiteralPath $Path) {(Get-Item -LiteralPath $Path).Length} else {0} }
function Wait-GodotProcessZero {
 param([Parameter(Mandatory=$true)][DateTime]$Deadline)
 $observed=[Collections.Generic.List[object]]::new(); $applicationError=$false
 while ($true) {
  $remaining=@(Get-GodotProcesses)
  foreach($window in @(Get-ErrorWindows)){$observed.Add($window); $applicationError=$true}
  if ($remaining.Count -eq 0 -or $applicationError -or [DateTime]::UtcNow -ge $Deadline){break}
  Start-Sleep -Milliseconds 250
 }
 return [pscustomobject]@{timed_out=(@(Get-GodotProcesses).Count -ne 0 -and -not $applicationError);has_application_error=$applicationError;application_error_windows=@($observed)}
}
if (-not (Test-Path -LiteralPath $GodotExe -PathType Leaf)) {throw 'Godot console executable does not exist.'}
$godot=(Resolve-Path -LiteralPath $GodotExe).Path
if (-not (Test-VandrelGodotConsoleExecutableName -ExecutableName ([IO.Path]::GetFileName($godot)))) {throw 'GodotExe must be the recognized console executable.'}
$sandbox=(Resolve-Path -LiteralPath $SandboxPath).Path
$output=Join-Path $sandbox 'output'; $monitor=Join-Path $output 'clean-body-godot-monitor.json'
if (-not (Test-Path -LiteralPath $output -PathType Container)) {throw 'Clean-body output directory does not exist.'}
if (@(Get-GodotProcesses).Count -ne 0) {throw 'Clean-body validation requires Godot process-zero.'}
$processZero=$true; $childEnvironment=Get-VandrelGodotChildEnvironment
$phases=@(
    [ordered]@{name='initial_import';args=@('--headless','--path',$sandbox,'--import','--quit-after','600')},
    [ordered]@{name='configure_import';args=@('--headless','--path',$sandbox,'--script','res://configure_clean_meshy_body_import.gd','--quit-after','600')},
    [ordered]@{name='retargeted_import';args=@('--headless','--path',$sandbox,'--import','--quit-after','600')},
    [ordered]@{name='technical_validate';args=@('--headless','--path',$sandbox,'--script','res://validate_clean_meshy_body.gd','--quit-after','600')},
    [ordered]@{name='visual_capture';args=@('--path',$sandbox,'--script','res://capture_clean_meshy_body.gd')}
)
 foreach($phase in $phases) {
  if (@(Get-GodotProcesses).Count -ne 0) {throw 'Godot process-zero failed before phase.'}
  $stdout=Join-Path $sandbox ('.clean-body-'+$phase.name+'-stdout.log'); $stderr=Join-Path $sandbox ('.clean-body-'+$phase.name+'-stderr.log'); $log=Join-Path $sandbox ('.clean-body-'+$phase.name+'-godot.log')
  $process=Start-Process -Environment $childEnvironment -FilePath $godot -ArgumentList (@($phase.args)+@('--log-file',$log)) -WorkingDirectory $sandbox -RedirectStandardOutput $stdout -RedirectStandardError $stderr -WindowStyle Hidden -PassThru
  $phaseStarted=[DateTime]::UtcNow; $crashPath=Join-Path $output ('clean-body-'+$phase.name+'-crash-evidence.json')
  $wait=Wait-VandrelGodotProcessWithCrashEvidence -Process $process -TimeoutSeconds $TimeoutSeconds -RunStartedUtc $phaseStarted -OutputPath $crashPath -RunLabel ('clean-body-'+$phase.name)
  # The Python caller assigns this supervisor and every descendant to one
  # kill-on-close Job Object. Wait for the phase-owned Godot children to settle;
  # on failure this script exits and that outer Job terminates only its own tree.
  $settle=Wait-GodotProcessZero -Deadline $phaseStarted.AddSeconds($TimeoutSeconds)
  $initialPhaseCrash=Get-Content -LiteralPath $crashPath -Raw | ConvertFrom-Json
  $phaseWindows=@($initialPhaseCrash.application_error_windows)+@($settle.application_error_windows)
  $phaseCrash=Write-VandrelGodotCrashEvidence -RunStartedUtc $phaseStarted -RunEndedUtc ([DateTime]::UtcNow) -OutputPath $crashPath -ObservedApplicationErrorWindows $phaseWindows -RootExitCode $wait.exit_code -RunLabel ('clean-body-'+$phase.name)
  foreach($window in @($phaseCrash.application_error_windows)) {$windows.Add($window)}
  $phaseTimedOut=[bool]$wait.timed_out -or [bool]$settle.timed_out
  $phaseCrashEvidence=[bool]$phaseCrash.has_crash_evidence
  $timedOut=$timedOut -or $phaseTimedOut; $cleanupFailed=$cleanupFailed -or [bool]$wait.cleanup_failed
  if ((Get-Length $stdout)+(Get-Length $stderr)+(Get-Length $log) -gt $MaximumOutputBytes) {$limited=$true}
  $exit=$wait.exit_code
  $results.Add([ordered]@{phase=$phase.name;exit_code=$exit;timed_out=$phaseTimedOut;cleanup_failed=[bool]$wait.cleanup_failed;has_crash_evidence=$phaseCrashEvidence;crash_evidence_path=[IO.Path]::GetFileName($crashPath);stdout_path=[IO.Path]::GetFileName($stdout);stderr_path=[IO.Path]::GetFileName($stderr);godot_log_path=[IO.Path]::GetFileName($log)})
  if ($exit -ne 0 -or $phaseTimedOut -or $wait.cleanup_failed -or $phaseCrashEvidence -or $limited) {throw "Clean-body Godot phase failed: $($phase.name)"}
 }
} catch {$failed=$_.Exception.Message}
finally {
 if (-not $authorityLoaded) {
  $ended=[DateTime]::UtcNow; if(-not(Test-Path -LiteralPath $output -PathType Container)){New-Item -ItemType Directory -Path $output -Force | Out-Null}
  $record=[ordered]@{schema_version='vandrel_foundry_clean_body_godot_monitor/1.0';policy='vandrel_monitored_godot_clean_body_corridor_2026-08-21';run_started_utc=$started.ToString('O');run_ended_utc=$ended.ToString('O');console_executable_name=$null;console_file_version=$null;godot_console_sha256=$null;supervisor_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath).Hash.ToLowerInvariant();runtime_guard_sha256=$null;crash_evidence_authority_sha256=$null;process_zero_preflight=$false;child_environment=@{};phase_results=@();outer_timeout_seconds_per_phase=$TimeoutSeconds;maximum_output_bytes=$MaximumOutputBytes;internal_iteration_bomb=600;post_exit_poll_seconds=5;timed_out=$false;output_limited=$false;cleanup_failed=$false;failure=$failed;application_error_windows=@();application_events=@();wer_and_dump_paths=@();final_godot_processes=@();has_crash_evidence=$false;passed=$false}
  [IO.File]::WriteAllText($monitor,(ConvertTo-Json $record -Depth 10)+[Environment]::NewLine,[Text.UTF8Encoding]::new($false)); $passed=$false
 } else {
 $deadline=[DateTime]::UtcNow.AddSeconds(5); while([DateTime]::UtcNow -lt $deadline){foreach($window in @(Get-ErrorWindows)){$windows.Add($window)};Start-Sleep -Milliseconds 250}
 $ended=[DateTime]::UtcNow
 $crashPath=Join-Path $output 'clean-body-canonical-crash-evidence.json'
 $crash=Write-VandrelGodotCrashEvidence -RunStartedUtc $started -RunEndedUtc $ended -OutputPath $crashPath -ObservedApplicationErrorWindows @($windows) -RunLabel 'clean-body-validation'
 $events=@($crash.application_events); $wer=@($crash.wer_and_dump_paths); $windows.Clear(); foreach($item in @($crash.application_error_windows)){$windows.Add($item)}
 $remaining=@(Get-GodotProcesses); $passed=$failed -eq '' -and -not $timedOut -and -not $limited -and $windows.Count -eq 0 -and $events.Count -eq 0 -and $wer.Count -eq 0 -and $remaining.Count -eq 0 -and $results.Count -eq $phases.Count
 $record=[ordered]@{schema_version='vandrel_foundry_clean_body_godot_monitor/1.0';policy='vandrel_monitored_godot_clean_body_corridor_2026-08-21';run_started_utc=$started.ToString('O');run_ended_utc=$ended.ToString('O');console_executable_name=$(if($godot){[IO.Path]::GetFileName($godot)}else{$null});console_file_version=$(if($godot){[Diagnostics.FileVersionInfo]::GetVersionInfo($godot).FileVersion}else{$null});godot_console_sha256=$(if($godot){(Get-FileHash -Algorithm SHA256 -LiteralPath $godot).Hash.ToLowerInvariant()}else{$null});supervisor_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $PSCommandPath).Hash.ToLowerInvariant();runtime_guard_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $RuntimeGuardPath).Hash.ToLowerInvariant();crash_evidence_authority_sha256=(Get-FileHash -Algorithm SHA256 -LiteralPath $CrashEvidenceScriptPath).Hash.ToLowerInvariant();process_zero_preflight=$processZero;child_environment=$childEnvironment;phase_results=@($results);outer_timeout_seconds_per_phase=$TimeoutSeconds;maximum_output_bytes=$MaximumOutputBytes;internal_iteration_bomb=600;post_exit_poll_seconds=5;timed_out=$timedOut;output_limited=$limited;cleanup_failed=$cleanupFailed;failure=$failed;application_error_windows=@($windows);application_events=$events;wer_and_dump_paths=@($wer);final_godot_processes=$remaining;has_crash_evidence=($windows.Count -gt 0 -or $events.Count -gt 0 -or $wer.Count -gt 0);passed=$passed}
 [IO.File]::WriteAllText($monitor,(ConvertTo-Json $record -Depth 10)+[Environment]::NewLine,[Text.UTF8Encoding]::new($false))
 }
}
if (-not $passed) {exit 1}; exit 0
