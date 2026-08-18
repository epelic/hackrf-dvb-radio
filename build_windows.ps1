$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = "$env:USERPROFILE\radioconda\python.exe"
if (-not (Test-Path -LiteralPath $Python)) { throw "Radioconda non trovato" }
Push-Location $Root
try {
    $RadioBin = "$env:USERPROFILE\radioconda\Library\bin"
    $env:Path = "$RadioBin;$env:Path"
    & $Python -m PyInstaller --noconfirm --clean --windowed --name HackRFDVBRadio --icon "assets\app.ico" --add-data "dvb_tx.py;." --add-data "assets\app.ico;assets" --add-binary "$RadioBin\tcl86t.dll;." --add-binary "$RadioBin\tk86t.dll;." --add-binary "$RadioBin\libcrypto-3-x64.dll;." --add-binary "$RadioBin\libssl-3-x64.dll;." --add-binary "$RadioBin\liblzma.dll;." --add-binary "$RadioBin\libbz2.dll;." --add-binary "$RadioBin\libexpat.dll;." app.py
    if ($LASTEXITCODE -ne 0) { throw "Creazione applicazione fallita" }
    $Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "C:\Program Files (x86)\Inno Setup 6\ISCC.exe", "C:\Program Files\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $Iscc) { winget install --id JRSoftware.InnoSetup --exact --silent --accept-package-agreements --accept-source-agreements }
    $Iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "C:\Program Files (x86)\Inno Setup 6\ISCC.exe", "C:\Program Files\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    & $Iscc installer.iss
    if ($LASTEXITCODE -ne 0) { throw "Creazione installer fallita" }
} finally { Pop-Location }
