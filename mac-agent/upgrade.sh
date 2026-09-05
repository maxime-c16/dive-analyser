#!/bin/bash
################################################################################
# Diving Analyser Mac Agent Upgrade Script
################################################################################

set -e
set -o pipefail

# Configuration
INSTALL_DIR="$HOME/.diveanalyzer"
VENV_DIR="$INSTALL_DIR/venv"
CONFIG_FILE="$INSTALL_DIR/config.yaml"
CODE_DIR="$INSTALL_DIR/code"
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

# Error handling
rollback() {
    error "Upgrade failed, rolling back..."

    # Restore original code
    if [ -d "$CODE_DIR.backup" ]; then
        log "Restoring previous version..."
        rm -rf "$CODE_DIR"
        mv "$CODE_DIR.backup" "$CODE_DIR"
    fi

    # Restore config if needed
    [ -f "$CONFIG_FILE.backup" ] && mv "$CONFIG_FILE.backup" "$CONFIG_FILE"

    # Restart agent
    launchctl kickstart -k "$LAUNCHD_DOMAIN/com.diveanalyzer.agent" 2>/dev/null || launchctl start com.diveanalyzer.agent 2>/dev/null || true

    error "Rollback complete"
    exit 1
}

trap rollback ERR

# Main
main() {
    echo ""
    echo "Diving Analyser Mac Agent Upgrade"
    echo "=================================="
    echo ""

    # Validate installation exists
    log "Checking current installation..."
    [ ! -d "$INSTALL_DIR" ] && { error "Installation not found at $INSTALL_DIR"; exit 1; }
    [ ! -f "$CONFIG_FILE" ] && { error "Configuration not found at $CONFIG_FILE"; exit 1; }
    [ ! -d "$VENV_DIR" ] && { error "Virtual environment not found at $VENV_DIR"; exit 1; }

    success "Installation found"
    echo ""

    # Backup current state
    log "Backing up current configuration..."
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup"
    [ -d "$CODE_DIR" ] && mv "$CODE_DIR" "$CODE_DIR.backup"

    # Stop agent
    log "Stopping agent..."
    launchctl stop com.diveanalyzer.agent 2>/dev/null || true
    sleep 2

    # Upgrade package
    log "Upgrading package..."
    source "$VENV_DIR/bin/activate"

    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    cp -r "$script_dir" "$CODE_DIR"

    cd "$CODE_DIR"
    pip install --upgrade -e . > /dev/null

    success "Package upgraded"
    echo ""

    # Restart agent
    log "Starting agent..."
    if [ -f "$PLIST_PATH" ]; then
        launchctl kickstart -k "$LAUNCHD_DOMAIN/com.diveanalyzer.agent" 2>/dev/null || launchctl start com.diveanalyzer.agent
    else
        warning "LaunchAgent plist not installed; run ./install.sh to enable autostart"
    fi
    sleep 3

    if pgrep -f "python3.*-m src.main" > /dev/null; then
        success "Agent restarted"
    else
        warning "Agent may not have restarted. Check logs:"
        echo "  tail -f $HOME/Library/Logs/diveanalyzer.log"
    fi

    # Cleanup backups
    log "Cleaning up backups..."
    rm -rf "$CODE_DIR.backup"
    rm -f "$CONFIG_FILE.backup"

    echo ""
    success "Upgrade complete!"
    echo ""
}

main "$@"
