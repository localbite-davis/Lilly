#!/usr/bin/env bash
# start.sh — start all Lily services
# Usage: bash start.sh [--no-docker] [--ngrok]
#
#   --no-docker   skip docker-compose (use SQLite + no Celery)
#   --ngrok       also launch ngrok and print the public URL

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

ok()    { echo -e "${GREEN}✓${NC}  $*"; }
info()  { echo -e "${CYAN}→${NC}  $*"; }
warn()  { echo -e "${YELLOW}!${NC}  $*"; }
die()   { echo -e "${RED}✗  $*${NC}" >&2; exit 1; }
label() { echo -e "\n${BOLD}$*${NC}"; }

USE_DOCKER=true
USE_NGROK=false
for arg in "$@"; do
    case $arg in
        --no-docker) USE_DOCKER=false ;;
        --ngrok)     USE_NGROK=true ;;
    esac
done

# PIDs to kill on exit
PIDS=()
cleanup() {
    echo -e "\n${YELLOW}Shutting down...${NC}"
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    if $USE_DOCKER; then
        info "Stopping Docker services..."
        docker-compose stop &>/dev/null || true
    fi
    echo -e "${GREEN}Done.${NC}"
}
trap cleanup EXIT INT TERM

# ── 1. Check virtual environment ──────────────────────────────────────────────
label "Checking environment"

if [ ! -d ".venv" ]; then
    die ".venv not found. Run 'bash setup.sh' first."
fi

if [ -z "$VIRTUAL_ENV" ]; then
    info "Activating virtual environment..."
    source .venv/bin/activate
fi
ok "Virtual environment active ($(python --version))"

# ── 2. Validate .env ──────────────────────────────────────────────────────────
if [ ! -f ".env" ]; then
    die ".env not found. Run 'bash setup.sh' first."
fi

set -a; source .env; set +a

MISSING=()
for key in ANTHROPIC_API_KEY DEEPGRAM_API_KEY ELEVENLABS_API_KEY; do
    val="${!key}"
    if [ -z "$val" ] || [[ "$val" == your_* ]] || [[ "$val" == sk-ant-... ]]; then
        MISSING+=("$key")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    warn "The following keys are not set in .env:"
    for k in "${MISSING[@]}"; do echo -e "    ${RED}$k${NC}"; done
    echo ""
    read -r -p "Continue anyway? (y/N) " confirm
    [[ "$confirm" =~ ^[Yy]$ ]] || exit 1
fi
ok ".env loaded"

# ── 3. Docker services (Postgres + Redis) ────────────────────────────────────
if $USE_DOCKER; then
    label "Starting Docker services"

    if ! command -v docker &>/dev/null; then
        warn "Docker not found — falling back to SQLite and skipping Celery."
        USE_DOCKER=false
    else
        docker-compose up -d --quiet-pull
        ok "Postgres and Redis containers started."

        # Wait for Postgres to accept connections (max 20s)
        info "Waiting for Postgres to be ready..."
        for i in $(seq 1 20); do
            if docker exec lily_postgres pg_isready -U lily_user -d lily_db &>/dev/null; then
                ok "Postgres ready."
                break
            fi
            if [ "$i" -eq 20 ]; then
                die "Postgres did not become ready in time. Check: docker logs lily_postgres"
            fi
            sleep 1
        done

        # Export DATABASE_URL if not already set
        export DATABASE_URL="${DATABASE_URL:-postgresql://lily_user:lily_password@localhost:5432/lily_db}"
    fi
else
    warn "--no-docker: using SQLite (lily_local.db) and skipping Celery worker."
    export DATABASE_URL="${DATABASE_URL:-sqlite:///./lily_local.db}"
fi

# ── 4. FastAPI server ─────────────────────────────────────────────────────────
label "Starting FastAPI server"

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload \
    > "$LOG_DIR/uvicorn.log" 2>&1 &
UVICORN_PID=$!
PIDS+=($UVICORN_PID)

# Wait for the server to respond
info "Waiting for server to come up..."
for i in $(seq 1 15); do
    if curl -sf http://localhost:8000/health &>/dev/null; then
        ok "FastAPI server running  →  http://localhost:8000"
        ok "API docs               →  http://localhost:8000/docs"
        break
    fi
    if [ "$i" -eq 15 ]; then
        die "Server did not start. Check logs/uvicorn.log for errors."
    fi
    sleep 1
done

# ── 5. Celery worker ──────────────────────────────────────────────────────────
if $USE_DOCKER; then
    label "Starting Celery worker"
    celery -A src.workers.celery_app worker --loglevel=info \
        > "$LOG_DIR/celery.log" 2>&1 &
    CELERY_PID=$!
    PIDS+=($CELERY_PID)
    sleep 2
    if kill -0 "$CELERY_PID" 2>/dev/null; then
        ok "Celery worker running"
    else
        warn "Celery worker failed to start — check logs/celery.log"
    fi
fi

# ── 6. ngrok (optional) ───────────────────────────────────────────────────────
if $USE_NGROK; then
    label "Starting ngrok tunnel"
    if ! command -v ngrok &>/dev/null; then
        warn "ngrok not found. Install from ngrok.com and add to PATH."
    else
        ngrok http 8000 --log=stdout > "$LOG_DIR/ngrok.log" 2>&1 &
        PIDS+=($!)
        sleep 2

        NGROK_URL=$(curl -sf http://localhost:4040/api/tunnels \
            | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])" 2>/dev/null || true)

        if [ -n "$NGROK_URL" ]; then
            ok "ngrok tunnel active"
            echo ""
            echo -e "  ${BOLD}Public URL:${NC}  ${CYAN}$NGROK_URL${NC}"
            echo -e "  ${DIM}Set this as your Twilio Voice webhook:${NC}"
            echo -e "  ${DIM}$NGROK_URL/api/twilio/voice/incoming${NC}"
        else
            warn "ngrok started but could not read tunnel URL. Check logs/ngrok.log or http://localhost:4040"
        fi
    fi
fi

# ── 7. Status summary ─────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  🌸 Lily is running${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  API          ${CYAN}http://localhost:8000${NC}"
echo -e "  Docs         ${CYAN}http://localhost:8000/docs${NC}"
if $USE_DOCKER; then
echo -e "  Postgres     ${CYAN}localhost:5432${NC}  (lily_db)"
echo -e "  Redis        ${CYAN}localhost:6379${NC}"
fi
echo ""
echo -e "  Logs:        ${DIM}tail -f logs/uvicorn.log${NC}"
if $USE_DOCKER; then
echo -e "               ${DIM}tail -f logs/celery.log${NC}"
fi
echo ""
echo -e "${DIM}  Press Ctrl+C to stop all services.${NC}"
echo ""

# ── 8. Tail logs ─────────────────────────────────────────────────────────────
tail -f "$LOG_DIR/uvicorn.log" &
PIDS+=($!)

# Keep script alive until Ctrl+C
wait
