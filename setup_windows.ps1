# ─────────────────────────────────────────────
#  Morse Decoder - Windows Setup Script
#  Run in PowerShell as administrator:
#  Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
#  .\setup_windows.ps1
# ─────────────────────────────────────────────

Write-Host ""
Write-Host "  ╔══════════════════════════════════╗"
Write-Host "  ║   Morse Decoder - Windows Setup  ║"
Write-Host "  ╚══════════════════════════════════╝"
Write-Host ""

# ── Python check ──────────────────────────────
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Host "  → Python not found. Installing via winget..."
    winget install Python.Python.3.12
    # Refresh PATH without restarting
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") `
              + ";" + [System.Environment]::GetEnvironmentVariable("PATH","User")
} else {
    $version = python --version 2>&1
    Write-Host "  ✓ $version already installed"
}

# ── Virtual environment ───────────────────────
Write-Host "  → Creating virtual environment..."
python -m venv venv
.\venv\Scripts\Activate.ps1

# ── Python dependencies ───────────────────────
Write-Host "  → Installing Python dependencies..."
pip install -r requirements.txt

Write-Host ""
Write-Host "  ✅ Python setup complete!"
Write-Host ""
Write-Host "  ─────────────────────────────────────────────────────"
Write-Host "  REMAINING MANUAL STEPS"
Write-Host "  ─────────────────────────────────────────────────────"
Write-Host ""
Write-Host "  FOR WEBSDR TESTING (virtual audio cable):"
Write-Host "  1. Download VB-Cable from https://vb-audio.com/Cable/"
Write-Host "  2. Run the installer as administrator, then restart"
Write-Host "  3. Open WebSDR at http://websdr.ewi.utwente.nl:8901"
Write-Host "  4. In Windows sound settings, set output to 'CABLE Input'"
Write-Host "  5. Run the decoder:"
Write-Host "     python main.py --device 'CABLE Output' --port 5001"
Write-Host "  6. Open http://localhost:5001 in your browser"
Write-Host ""
Write-Host "  FOR RTL-SDR HARDWARE:"
Write-Host "  1. Plug in your RTL-SDR"
Write-Host "  2. Download Zadig from https://zadig.akeo.ie/"
Write-Host "  3. In Zadig: Options → List All Devices"
Write-Host "     Select 'Bulk-In, Interface (Interface 0)'"
Write-Host "     Install WinUSB driver"
Write-Host "  4. Download RTL-SDR tools from https://ftp.osmocom.org/binaries/windows/rtl-sdr/"
Write-Host "     Extract and add the folder to your PATH"
Write-Host "  5. Run: python main.py --source sdr --freq 7.050"
Write-Host ""
Write-Host "  QUICK START ALIAS (optional):"
Write-Host "  Add this to your PowerShell profile (\$PROFILE):"
Write-Host "  function morse { cd ~\Development\morse-decoder; .\venv\Scripts\Activate.ps1 }"
Write-Host "  Then just type 'morse' in any PowerShell window."
Write-Host "  ─────────────────────────────────────────────────────"
Write-Host ""
