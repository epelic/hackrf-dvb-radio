$ErrorActionPreference = "Stop"

if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    throw "Windows Package Manager (winget) non disponibile. Aggiornare 'Programma di installazione app' dal Microsoft Store."
}

$packages = @(
    "Gyan.FFmpeg.Essentials",
    "TSDuck.TSDuck",
    "ryanvolz.radioconda"
)

foreach ($package in $packages) {
    & winget install --id $package --exact --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
    if ($LASTEXITCODE -ne 0) {
        # Winget usa talvolta un codice non-zero quando il pacchetto è già aggiornato.
        $installed = winget list --id $package --exact --accept-source-agreements 2>$null
        if (-not ($installed -match [regex]::Escape($package))) {
            throw "Installazione automatica non riuscita: $package"
        }
    }
}
