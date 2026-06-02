$raw = [Console]::In.ReadToEnd()
if (-not $raw.Trim()) { exit 0 }

try {
    $data = $raw | ConvertFrom-Json
} catch {
    exit 0
}

$tool = $data.tool_name
$inp  = $data.tool_input

function Test-EnvFile($path) {
    if (-not $path) { return $false }
    $name = [System.IO.Path]::GetFileName($path.ToString())
    return ($name -match '^\.env' -and $name -ne '.env.example')
}

function Test-EnvInCommand($cmd) {
    if (-not $cmd) { return $false }
    $stripped = $cmd -replace '\.env\.example', ''
    return ($stripped -match '\.env\b')
}

$blocked = $false
$reason  = $null

switch ($tool) {
    { $_ -in 'Read', 'Edit', 'Write' } {
        if (Test-EnvFile $inp.file_path) {
            $blocked = $true
            $reason  = "Access denied: '$($inp.file_path)' is off-limits. Only .env.example may be accessed."
        }
    }
    'Glob' {
        $pat = $inp.pattern
        if ($pat) {
            $stripped = $pat -replace '\.env\.example', ''
            if ($stripped -match '\.env') {
                $blocked = $true
                $reason  = "Access denied: glob pattern targets .env files. Only .env.example is accessible."
            }
        }
    }
    'Grep' {
        if (Test-EnvFile $inp.path) {
            $blocked = $true
            $reason  = "Access denied: '$($inp.path)' is off-limits. Only .env.example may be accessed."
        }
        if (-not $blocked -and $inp.glob) {
            $stripped = $inp.glob -replace '\.env\.example', ''
            if ($stripped -match '\.env') {
                $blocked = $true
                $reason  = "Access denied: grep glob filter targets .env files. Only .env.example is accessible."
            }
        }
    }
    { $_ -in 'Bash', 'PowerShell' } {
        if (Test-EnvInCommand $inp.command) {
            $blocked = $true
            $reason  = "Access denied: command references a .env file. Only .env.example is accessible."
        }
    }
}

if ($blocked) {
    [Console]::Out.WriteLine((@{ decision = 'block'; reason = $reason } | ConvertTo-Json -Compress))
    exit 2
}

exit 0
