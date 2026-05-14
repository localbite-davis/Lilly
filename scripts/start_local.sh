#!/usr/bin/env bash
# start_local.sh — local dev startup (conda + NeonDB + ngrok)
# Usage: bash start_local.sh

set -e

CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()   { echo -e "${GREEN}✓${NC}  $*"; }
info() { echo -e "${CYAN}→${NC}  $*"; }
warn() { echo -e "${YELLOW}!${NC}  $*"; }
die()  { echo -e "${RED}✗  $*${NC}" >&2; exit 1; }

PIDS=()
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    echo -e "${GREEN}Done.${NC}"
}
trap cleanup EXIT INT TERM

# ── 1. Conda env ──────────────────────────────────────────────────────────────
info "Checking conda environment..."

# Find the lily env's Python directly — avoids conda run shell init issues
CONDA_BASE=$(conda info --base 2>/dev/null) || die "conda not found in PATH"
LILY_PYTHON="$CONDA_BASE/envs/lily/bin/python"

if [ ! -f "$LILY_PYTHON" ]; then
    die "conda env 'lily' not found. Create it: conda create -n lily python=3.11 && conda activate lily && pip install -r requirements.txt"
fi
ok "conda env 'lily' found at $CONDA_BASE/envs/lily"

# ── 2. .env ───────────────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    die ".env not found in $(pwd)"
fi

# Use Python to parse .env safely — avoids bash mishandling & and other special chars
MISSING=$("$LILY_PYTHON" - <<'PYEOF'
import sys
vals = {}
with open(".env") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        vals[k.strip()] = v.strip()

required = ["ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "DATABASE_URL", "PINECONE_API_KEY"]
missing = [k for k in required if not vals.get(k) or vals[k].startswith("your_")]
print("\n".join(missing))
PYEOF
)

if [ -n "$MISSING" ]; then
    warn "These keys are missing or placeholder in .env:"
    while IFS= read -r k; do echo -e "    ${RED}$k${NC}"; done <<< "$MISSING"
    read -r -p "Continue anyway? (y/N) " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi
ok ".env loaded"

# ── 3. FastAPI server ─────────────────────────────────────────────────────────
info "Starting FastAPI server on port 8000..."
mkdir -p logs
"$LILY_PYTHON" -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload \
    > logs/uvicorn.log 2>&1 &
UVICORN_PID=$!
PIDS+=($UVICORN_PID)

for i in $(seq 1 20); do
    if curl -sf http://localhost:8000/health &>/dev/null; then
        ok "FastAPI running → http://localhost:8000"
        break
    fi
    if [ "$i" -eq 20 ]; then
        die "Server didn't start. Check logs/uvicorn.log"
    fi
    sleep 1
done

# ── 4. Tunnel (ngrok or cloudflared) ─────────────────────────────────────────
PUBLIC_URL=""

# Try cloudflared first — no account needed
if command -v cloudflared &>/dev/null; then
    info "Starting Cloudflare tunnel (no account needed)..."
    cloudflared tunnel --url http://localhost:8000 --no-autoupdate \
        > logs/tunnel.log 2>&1 &
    PIDS+=($!)

    # Poll until the URL appears in the log (up to 30s)
    for i in $(seq 1 30); do
        PUBLIC_URL=$(grep -o 'https://[a-z0-9.-]*\.trycloudflare\.com' logs/tunnel.log 2>/dev/null | head -1)
        if [ -n "$PUBLIC_URL" ]; then
            ok "Cloudflare tunnel active (${i}s)"
            break
        fi
        if [ "$i" -eq 30 ]; then
            warn "Cloudflare tunnel didn't print a URL after 30s — check logs/tunnel.log"
        fi
        sleep 1
    done

# Fall back to ngrok
elif command -v ngrok &>/dev/null; then
    # Check if authtoken is configured
    if ! ngrok config check &>/dev/null 2>&1; then
        echo ""
        warn "ngrok requires a free account token. Two options:"
        echo ""
        echo -e "  ${BOLD}Option A — ngrok (free account):${NC}"
        echo -e "  1. Sign up at ${CYAN}https://dashboard.ngrok.com/signup${NC}"
        echo -e "  2. Run: ${CYAN}ngrok config add-authtoken <your-token>${NC}"
        echo -e "  3. Re-run this script"
        echo ""
        echo -e "  ${BOLD}Option B — Cloudflare (no account):${NC}"
        echo -e "  Run: ${CYAN}brew install cloudflared${NC}  then re-run this script"
        echo ""
    else
        info "Starting ngrok tunnel..."
        ngrok http 8000 --log=stdout > logs/tunnel.log 2>&1 &
        PIDS+=($!)
        sleep 3
        PUBLIC_URL=$(curl -sf http://localhost:4040/api/tunnels \
            | "$LILY_PYTHON" -c "
import sys, json
tunnels = json.load(sys.stdin).get('tunnels', [])
https = [t for t in tunnels if t['public_url'].startswith('https')]
print(https[0]['public_url'] if https else (tunnels[0]['public_url'] if tunnels else ''))
" 2>/dev/null || true)
        [ -n "$PUBLIC_URL" ] && ok "ngrok tunnel active"
    fi

else
    warn "No tunnel tool found. Install one:"
    echo -e "  Cloudflare (no account): ${CYAN}brew install cloudflared${NC}"
    echo -e "  ngrok (free account):    ${CYAN}brew install ngrok${NC}"
fi

if [ -n "$PUBLIC_URL" ]; then
    echo ""
    echo -e "  ${BOLD}Public URL:${NC}        ${CYAN}$PUBLIC_URL${NC}"
    echo -e "  ${BOLD}Twilio webhook:${NC}    ${CYAN}${PUBLIC_URL}/api/twilio/voice/incoming${NC}"
    echo ""
    echo -e "  ${DIM}→ Twilio Console → Phone Numbers → your number → Voice webhook${NC}"
fi

# ── 5. Summary ────────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Lily is running (local dev)${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  API       ${CYAN}http://localhost:8000${NC}"
echo -e "  Docs      ${CYAN}http://localhost:8000/docs${NC}"
echo -e "  Logs      ${DIM}tail -f logs/uvicorn.log${NC}"
echo ""
echo -e "${DIM}  Press Ctrl+C to stop.${NC}"
echo ""

# ── 6. Tail server logs ───────────────────────────────────────────────────────
tail -f logs/uvicorn.log &
PIDS+=($!)
wait
