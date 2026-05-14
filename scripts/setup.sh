#!/usr/bin/env bash
# setup.sh — one-shot environment setup for Lily
# Usage: bash setup.sh

set -e  # exit on first error

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${CYAN}→${NC}  $*"; }
warn() { echo -e "${YELLOW}!${NC}  $*"; }
die()  { echo -e "${RED}✗  $*${NC}" >&2; exit 1; }

echo -e "\n${BOLD}🌸  Lily — environment setup${NC}\n"

# ── 1. Python version check (3.10+ required for X | Y type union syntax) ─────
info "Checking Python version..."
PYTHON=$(command -v python3 || command -v python || die "Python not found. Install Python 3.10+.")
PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    die "Python 3.10+ required (found $PY_VERSION). Install from python.org or use pyenv."
fi
ok "Python $PY_VERSION"

# ── 2. Create virtual environment ─────────────────────────────────────────────
VENV_DIR=".venv"
if [ -d "$VENV_DIR" ]; then
    warn "Virtual environment already exists at $VENV_DIR — skipping creation."
else
    info "Creating virtual environment at $VENV_DIR..."
    $PYTHON -m venv "$VENV_DIR"
    ok "Virtual environment created."
fi

# Activate
source "$VENV_DIR/bin/activate"
ok "Virtual environment activated."

# ── 3. Upgrade pip silently ───────────────────────────────────────────────────
info "Upgrading pip..."
pip install --upgrade pip --quiet
ok "pip up to date."

# ── 4. Install dependencies ───────────────────────────────────────────────────
info "Installing dependencies from requirements.txt..."
pip install -r requirements.txt --quiet
ok "Dependencies installed."

# ── 5. Create .env from .env.example ─────────────────────────────────────────
if [ -f ".env" ]; then
    warn ".env already exists — skipping. Edit it manually if you need to update keys."
else
    if [ -f ".env.example" ]; then
        cp .env.example .env
        ok ".env created from .env.example."
        echo ""
        echo -e "${YELLOW}  ┌─────────────────────────────────────────────────────────┐${NC}"
        echo -e "${YELLOW}  │  Open .env and fill in your API keys before running.    │${NC}"
        echo -e "${YELLOW}  │                                                         │${NC}"
        echo -e "${YELLOW}  │  Required:                                              │${NC}"
        echo -e "${YELLOW}  │    ANTHROPIC_API_KEY   → console.anthropic.com          │${NC}"
        echo -e "${YELLOW}  │    DEEPGRAM_API_KEY    → console.deepgram.com (free)    │${NC}"
        echo -e "${YELLOW}  │    ELEVENLABS_API_KEY  → elevenlabs.io (free tier)      │${NC}"
        echo -e "${YELLOW}  │                                                         │${NC}"
        echo -e "${YELLOW}  │  Only needed for real phone calls:                      │${NC}"
        echo -e "${YELLOW}  │    TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN               │${NC}"
        echo -e "${YELLOW}  └─────────────────────────────────────────────────────────┘${NC}"
        echo ""
    else
        warn ".env.example not found — creating a blank .env. Fill it in manually."
        touch .env
    fi
fi

# ── 6. Check Docker (for Postgres) ───────────────────────────────────────────
if command -v docker &>/dev/null; then
    ok "Docker found — run 'docker-compose up -d' to start the database."
else
    warn "Docker not found. You'll need it to run the database (docker.com)."
fi

# ── 7. Done ───────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}Setup complete. Next steps:${NC}"
echo ""
echo -e "  ${CYAN}1.${NC} Fill in your keys:          ${BOLD}nano .env${NC}"
echo -e "  ${CYAN}2.${NC} Start the database:          ${BOLD}docker-compose up -d${NC}"
echo -e "  ${CYAN}3.${NC} Run the server:              ${BOLD}uvicorn src.main:app --reload --port 8000${NC}"
echo -e "  ${CYAN}4.${NC} Expose to Twilio (new tab):  ${BOLD}ngrok http 8000${NC}"
echo -e "  ${CYAN}5.${NC} Run smoke tests:             ${BOLD}pytest tests/test_speech_pipeline.py -v -s${NC}"
echo ""
echo -e "  ${CYAN}Activate venv in future sessions:${NC} ${BOLD}source .venv/bin/activate${NC}"
echo ""
