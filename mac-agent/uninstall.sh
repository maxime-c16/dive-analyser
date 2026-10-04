#!/bin/bash
################################################################################
# Diving Analyser Mac Agent Uninstaller
################################################################################

set -e
set -o pipefail

# Configuration
INSTALL_DIR="$HOME/.diveanalyzer"
VENV_DIR="$INSTALL_DIR/venv"
LOG_DIR="$HOME/Library/Logs"
PLIST_PATH="$HOME/Library/LaunchAgents/com.diveanalyzer.agent.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log() {
    echo -e "${BLUE}ℹ${NC} $1"
}

success() {
    echo -e "${GREEN}✓${NC} $1"
}

error() {
    echo -e "${RED}✗${NC} $1"
}

warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

# Main
main() {
    echo ""
    echo "Diving Analyser Mac Agent Uninstaller"
    echo "======================================"
    echo ""

    # Parse flags
    KEEP_CONFIG=true
    while [[ $# -gt 0 ]]; do
        case $1 in
            --no-keep-config) KEEP_CONFIG=false; shift ;;
            *) shift ;;
        esac
    done

    # Confirm uninstallation
    echo "This will remove Diving Analyser Mac Agent"
    [ "$KEEP_CONFIG" = true ] && echo "  - Configuration file will be KEPT"
    [ "$KEEP_CONFIG" = false ] && echo "  - Configuration file will be DELETED"
    echo "  - Virtual environment will be DELETED"
    echo "  - Offline queue will be DELETED"
    echo "  - Logs will be DELETED"
    echo ""

    read -p "$(echo -e ${BLUE}?${NC}) Continue? (y/N): " confirm
    [[ ! "$confirm" =~ ^[Yy]$ ]] && { log "Cancelled"; exit 0; }

    echo ""

    # Stop agent
    log "Stopping agent..."
    launchctl stop com.diveanalyzer.agent 2>/dev/null || true
    pkill -f "python3.*-m src.main" 2>/dev/null || true
    sleep 2

    # Unload LaunchAgent
    log "Unloading LaunchAgent..."
    launchctl bootout "$LAUNCHD_DOMAIN" "$PLIST_PATH" 2>/dev/null || launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"

    # Remove files
    log "Removing installation..."
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    rm -rf "$INSTALL_DIR/code"
    rm -f "$INSTALL_DIR/.env"
    rm -f "$INSTALL_DIR/queue.json"
    rm -f "$INSTALL_DIR/heartbeat"
    rm -f "$INSTALL_DIR/checkpoint.json"
    rm -f "$INSTALL_DIR/install.log"

    # Remove config (if requested)
    if [ "$KEEP_CONFIG" = false ]; then
        rm -f "$INSTALL_DIR/config.yaml"
    fi

    # Remove logs
    log "Removing logs..."
    rm -f "$LOG_DIR/diveanalyzer"*.log*

    # Remove directory (if empty)
    rmdir "$INSTALL_DIR" 2>/dev/null || log "Note: $INSTALL_DIR not empty, keeping"

    # Final verification
    if pgrep -f "python3.*-m src.main" > /dev/null; then
        warning "Agent still running, force killing..."
        pkill -9 -f "python3.*-m src.main"
    fi

    echo ""
    success "Uninstallation complete!"
    echo ""
}

main "$@"
