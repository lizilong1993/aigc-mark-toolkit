param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ForwardArgs
)

$RepoRoot = Split-Path -Parent $PSScriptRoot
$CliRoot = Join-Path $RepoRoot "cli"
$ExistingPythonPath = $env:PYTHONPATH
if ([string]::IsNullOrWhiteSpace($ExistingPythonPath)) {
    $env:PYTHONPATH = $CliRoot
}
else {
    $env:PYTHONPATH = "$CliRoot;$ExistingPythonPath"
}

$env:PYTHONHASHSEED = "0"
$PythonSelector = "-3"
try {
    & py -3.10 -c "import sys; print(sys.version_info[:2])" *> $null
    if ($LASTEXITCODE -eq 0) {
        $PythonSelector = "-3.10"
    }
}
catch {
}

& py $PythonSelector -m aigc_mark_toolkit.cli @ForwardArgs
exit $LASTEXITCODE
