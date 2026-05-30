#!/bin/bash
# ─────────────────────────────────────────────
#  Morse Decoder - Mac Setup Script
# ─────────────────────────────────────────────

set -e

echo ""
echo "  ╔══════════════════════════════════╗"
echo "  ║   Morse Decoder - Mac Setup      ║"
echo "  ╚══════════════════════════════════╝"
echo ""

# ── Homebrew ──────────────────────────────────
if ! command -v brew &> /dev/null; then
    echo "  → Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "  ✓ Homebrew already installed"
fi

# ── RTL-SDR (for when your hardware arrives) ──
echo "  → Installing librtlsdr..."
brew install librtlsdr

# ── BlackHole (virtual audio for WebSDR testing, no hardware needed) ──
echo "  → Installing BlackHole virtual audio cable..."
brew install --cask blackhole-2ch

# ── Python virtual environment ────────────────
echo "  → Creating Python virtual environment..."
python3 -m venv venv
source venv/bin/activate

echo "  → Installing Python dependencies..."
pip install -r requirements.txt

echo ""
echo "  ✅ Setup complete!"
echo ""
echo "  ─────────────────────────────────────────────────────"
echo "  TESTING WITHOUT SDR HARDWARE (WebSDR method):"
echo "  ─────────────────────────────────────────────────────"
echo "  1. Open: Applications > Utilities > Audio MIDI Setup"
echo "  2. Click '+' at bottom left → 'Create Multi-Output Device'"
echo "  3. Check 'Built-in Output' AND 'BlackHole 2ch'"
echo "  4. Right-click it → 'Use This Device For Sound Output'"
echo "  5. Open http://websdr.org in your browser"
echo "  6. Tune to 7.000–7.100 MHz (40m CW band)"
echo "  7. Run the decoder:"
echo ""
echo "     source venv/bin/activate"
echo "     python main.py --device 'BlackHole 2ch'"
echo ""
echo "  8. Open http://localhost:5000 — you should see text decoding!"
echo "  ─────────────────────────────────────────────────────"
echo ""
echo "  OTHER USEFUL COMMANDS:"
echo "  python main.py --list              # List all audio devices"
echo "  python main.py --device 'MacBook'  # Use built-in mic (for testing)"
echo "  python main.py --source sdr --freq 7.050  # RTL-SDR (when ready)"
echo ""
