#!/bin/bash
################################################################################
# Diving Analyser Mac Agent Installer
################################################################################

set -e
set -o pipefail

# Configuration
INSTALL_DIR="$HOME/.diveanalyzer"
VENV_DIR="$INSTALL_DIR/venv"
CODE_DIR="$INSTALL_DIR/code"
CONFIG_FILE="$INSTALL_DIR/config.yaml"
LOG_DIR="$HOME/Library/Logs"
INSTALL_LOG="$INSTALL_DIR/install.log"
PLIST_PATH="$HOME/Library/LaunchAgents/com.diveanalyzer.agent.plist"
LAUNCHD_DOMAIN="gui/$(id -u)"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging functions
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$INSTALL_LOG"
    echo -e "${BLUE}ℹ${NC} $1"
}

success() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] SUCCESS: $1" >> "$INSTALL_LOG"
    echo -e "${GREEN}✓${NC} $1"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $1" >> "$INSTALL_LOG"
    echo -e "${RED}✗${NC} $1"
}

warning() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: $1" >> "$INSTALL_LOG"
    echo -e "${YELLOW}⚠${NC} $1"
}

cleanup_on_error() {
    error "Installation failed"
    launchctl bootout "$LAUNCHD_DOMAIN" "$PLIST_PATH" 2>/dev/null || launchctl unload "$PLIST_PATH" 2>/dev/null || true
    pkill -f diveanalyzer 2>/dev/null || true
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    [ -d "$CODE_DIR" ] && rm -rf "$CODE_DIR"
    [ -f "$PLIST_PATH" ] && rm -f "$PLIST_PATH"
    error "Rollback complete. Log: $INSTALL_LOG"
    exit 1
}

trap cleanup_on_error ERR

# Pre-flight checks
preflight_checks() {
    log "Running pre-flight checks..."
    
    if ! command -v python3.12 &> /dev/null; then
        error "Python 3.12 not found. Install with: brew install python@3.12"
        exit 1
    fi
    
    success "Python $(python3.12 --version 2>&1 | awk '{print $2}') found"
    echo ""
}

# Configure agent
configure_agent() {
    log "Setting up configuration..."
    
    mkdir -p "$INSTALL_DIR"
    mkdir -p "$LOG_DIR"
    
    if [ -f "$CONFIG_FILE" ]; then
        warning "Configuration file already exists"
        return 0
    fi
    
    read -p "$(echo -e ${BLUE}?${NC}) Server URL [https://192.168.1.57:8000]: " server_url
    server_url="${server_url:-https://192.168.1.57:8000}"

    read -sp "$(echo -e ${BLUE}?${NC}) API Key (hidden): " api_key
    echo ""
    
    [ -z "$api_key" ] && { error "API Key required"; exit 1; }
    
    cp "$(dirname "$0")/config.example.yaml" "$CONFIG_FILE"
    sed -i '' "s|url: \"https://192.168.1.57:8000\"|url: \"$server_url\"|" "$CONFIG_FILE"
    sed -i '' "s|api_key: \"sk_live_your_api_key_here_minimum_40_characters\"|api_key: \"$api_key\"|" "$CONFIG_FILE"
    success "Configuration created at $CONFIG_FILE"
    echo ""
}

# Setup virtual environment
setup_venv() {
    log "Creating Python virtual environment..."
    [ -d "$VENV_DIR" ] && rm -rf "$VENV_DIR"
    python3.12 -m venv "$VENV_DIR"
    source "$VENV_DIR/bin/activate"
    pip install --upgrade pip setuptools wheel > /dev/null
    success "Virtual environment ready"
    echo ""
}

# Install package
install_package() {
    log "Installing Diving Analyser Mac Agent..."
    source "$VENV_DIR/bin/activate"
    
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    [ -d "$CODE_DIR" ] && rm -rf "$CODE_DIR"
    cp -r "$script_dir" "$CODE_DIR"
    
    cd "$CODE_DIR"
    pip install -e . > /dev/null
    success "Package installed"
    echo ""
}

# Validate configuration
validate_configuration() {
    log "Validating configuration..."
    
    if [ ! -f "$CONFIG_FILE" ]; then
        error "Configuration file not found"
        exit 1
    fi
    
    grep -q "^server:" "$CONFIG_FILE" || { error "Missing server section"; exit 1; }
    grep -q "url:" "$CONFIG_FILE" || { error "Missing server.url"; exit 1; }
    grep -q "api_key:" "$CONFIG_FILE" || { error "Missing server.api_key"; exit 1; }
    
    success "Configuration valid"
    echo ""
}

# Setup LaunchAgent
setup_launchagent() {
    log "Installing LaunchAgent..."

    mkdir -p "$(dirname "$PLIST_PATH")"

    # Unload any previously loaded agent.
    launchctl bootout "$LAUNCHD_DOMAIN" "$PLIST_PATH" 2>/dev/null || launchctl unload "$PLIST_PATH" 2>/dev/null || true

    # Generate plist with fully-expanded paths (launchd does not expand ~)
    cat > "$PLIST_PATH" << PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.diveanalyzer.agent</string>

  <key>ProgramArguments</key>
  <array>
    <string>$VENV_DIR/bin/python3</string>
    <string>-m</string>
    <string>src.main</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$CODE_DIR</string>

  <key>RunAtLoad</key>
  <true/>

  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>
    <false/>
  </dict>

  <key>ThrottleInterval</key>
  <integer>30</integer>

  <key>StandardOutPath</key>
  <string>$HOME/Library/Logs/diveanalyzer.log</string>

  <key>StandardErrorPath</key>
  <string>$HOME/Library/Logs/diveanalyzer.error.log</string>

  <key>WaitForNetwork</key>
  <true/>
</dict>
</plist>
PLIST_EOF

    chmod 644 "$PLIST_PATH"

    plutil -lint "$PLIST_PATH" > /dev/null || { error "Plist validation failed"; exit 1; }

    launchctl bootstrap "$LAUNCHD_DOMAIN" "$PLIST_PATH" 2>/dev/null || launchctl load "$PLIST_PATH"
    sleep 1

    if launchctl print "$LAUNCHD_DOMAIN/com.diveanalyzer.agent" >/dev/null 2>&1 || launchctl list 2>/dev/null | grep -q "com.diveanalyzer.agent"; then
        success "LaunchAgent loaded"
    else
        warning "LaunchAgent may need manual restart"
    fi
    echo ""
}

# Start agent
start_agent() {
    log "Starting agent..."
    launchctl start com.diveanalyzer.agent
    sleep 3
    
    if pgrep -f "python3.*-m src.main" > /dev/null; then
        success "Agent started (PID: $(pgrep -f "python3.*-m src.main" | head -1))"
    else
        warning "Agent may not have started. Check logs:"
        echo "  tail -f $LOG_DIR/diveanalyzer.log"
    fi
    echo ""
}

# Show summary
show_summary() {
    echo "=========================================="
    echo -e "${GREEN}Installation Complete!${NC}"
    echo "=========================================="
    echo ""
    echo "Next Steps:"
    echo "  1. Verify: launchctl list | grep diveanalyzer"
    echo "  2. Logs: tail -f $LOG_DIR/diveanalyzer.log"
    echo "  3. Config: nano $CONFIG_FILE"
    echo ""
    echo "Config: $CONFIG_FILE"
    echo "Logs: $LOG_DIR"
    echo ""
}

# Main
main() {
    echo ""
    echo "Diving Analyser Mac Agent Installer"
    echo "=================================="
    echo ""
    
    mkdir -p "$INSTALL_DIR"
    > "$INSTALL_LOG"
    
    preflight_checks
    configure_agent
    setup_venv
    install_package
    validate_configuration
    setup_launchagent
    start_agent
    show_summary
    
    success "Installation complete!"
}

main "$@"
