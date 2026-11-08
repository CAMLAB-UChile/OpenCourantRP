# Used by run_deck.bat: OpenCourantRP shows /ANIM output only, so the engine runs a copy of the engine deck
# without the /H3D cards (and their data lines) and with a standard /ANIM block (plus the solid cards when the starter has solids) when the deck has none.
# Usage: prepare_engine.ps1 IN.rad OUT.rad [-Combined]     OUT.rad is written only when the deck needs a change.
# With -Combined, IN.rad is a single deck (engine block, then the starter from /BEGIN): the starter half is written next
# to OUT.rad under the name of IN.rad, and OUT.rad is always written, both with the #RADIOSS first line the solver needs.
param([string]$In, [string]$Out, [switch]$Combined)

$inv = [Globalization.CultureInfo]::InvariantCulture
$ci = [StringComparison]::OrdinalIgnoreCase
$keep = New-Object System.Collections.Generic.List[string]
$skip = $false; $h3d = 0; $anim = $false; $added = $false; $afterRun = $false; $tend = $null

$lines = @(Get-Content -LiteralPath $In)
$starterLines = @()
if ($Combined) {
    $begin = 0
    while ($begin -lt $lines.Count -and -not $lines[$begin].StartsWith('/BEGIN', $ci)) { $begin++ }
    if ($begin -ge $lines.Count) { Write-Host "ERROR: $(Split-Path -Leaf $In) has no /BEGIN card: it is not a combined deck."; exit 1 }
    if ($begin -eq 0) { Write-Host "ERROR: $(Split-Path -Leaf $In) has no engine data before /BEGIN."; exit 1 }
    $starterLines = @('#RADIOSS STARTER') + $lines[$begin..($lines.Count - 1)]
    $lines = @('#RADIOSS ENGINE') + $lines[0..($begin - 1)]
    Set-Content -LiteralPath (Join-Path (Split-Path -Parent $Out) (Split-Path -Leaf $In)) -Value $starterLines -Encoding ascii
    Write-Host "Combined deck $(Split-Path -Leaf $In): split into a starter and an engine deck in $(Split-Path -Parent $Out)."
} else {
    $starter = $In -replace '_0001\.rad$', '_0000.rad'
    if (Test-Path -LiteralPath $starter) { $starterLines = @(Get-Content -LiteralPath $starter) }
}

foreach ($line in $lines) {
    if ($line.StartsWith('/')) {
        $skip = $line.StartsWith('/H3D', $ci)
        if ($skip) { $h3d++ }
        if ($line.StartsWith('/ANIM', $ci) -and -not $line.StartsWith('/ANIM/GZIP', $ci)) { $anim = $true }
        $afterRun = $line.StartsWith('/RUN', $ci)
    } elseif ($afterRun -and $line.Trim() -ne '' -and -not $line.StartsWith('#')) {
        $afterRun = $false
        $tend = [double]::Parse(($line.Trim() -split '\s+')[0], $inv)
    }
    if (-not $skip) { $keep.Add($line) }
}

if ($h3d -gt 0) {
    Write-Host "WARNING: $h3d /H3D card(s) of $(Split-Path -Leaf $In) ignored, so no .h3d file is written. RP shows the /ANIM output only."
}

if (-not $anim) {
    if ($null -eq $tend -or $tend -le 0) {
        Write-Host "WARNING: $(Split-Path -Leaf $In) has no /ANIM cards and no end time after /RUN, so none were added: there will be nothing to show."
    } else {
        $dt = ($tend / 80).ToString('G6', $inv)
        $cards = New-Object System.Collections.Generic.List[string]
        $cards.AddRange([string[]]@(
            '/ANIM/DT', "0. $dt",
            '/ANIM/ELEM/EPSP', '/ANIM/ELEM/VONM',
            '/ANIM/SHELL/TENS/STRESS/3', '/ANIM/SHELL/TENS/STRAIN/3',
            '/ANIM/SHELL/TENS/STRESS/UPPER', '/ANIM/SHELL/TENS/STRESS/LOWER',
            '/ANIM/SHELL/TENS/STRAIN/UPPER', '/ANIM/SHELL/TENS/STRAIN/LOWER',
            '/ANIM/SHELL/TENS/STRESS/MEMB', '/ANIM/SHELL/TENS/STRAIN/MEMB',
            '/ANIM/SHELL/EPSP/UPPER', '/ANIM/SHELL/EPSP/LOWER',
            '/ANIM/VECT/DISP', '/ANIM/VECT/VEL', '/ANIM/VECT/CONT'))
        if ($starterLines -match '^/(BRICK|BRIC20|TETRA4|TETRA10|PENTA6)/') {
            $cards.AddRange([string[]]@('/ANIM/BRICK/TENS/STRESS/000', '/ANIM/BRICK/TENS/STRAIN/000', '/ANIM/BRICK/VONM', '/ANIM/BRICK/EPSP'))
        }
        $end = $keep.FindIndex({ param($l) $l.StartsWith('/END', $ci) })  # the cards go before /END/ENGINE
        if ($end -ge 0) { $keep.InsertRange($end, $cards) } else { $keep.AddRange($cards) }
        Write-Host "WARNING: $(Split-Path -Leaf $In) has no /ANIM cards: the standard block was added to the run copy (80 frames, one every $dt time units)."
        $added = $true
    }
}

if ($h3d -gt 0 -or $added -or $Combined) {
    Set-Content -LiteralPath $Out -Value $keep -Encoding ascii
}
