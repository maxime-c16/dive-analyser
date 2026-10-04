#!/bin/bash
# dive-analyser Health & Diagnostics Script
# Monitors backend, frontend, nginx, and catches 502 errors in a feedback loop

set -e

LOGFILE="/tmp/dive-analyser-diagnostics.log"
ERRORFILE="/tmp/dive-analyser-errors.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "[$TIMESTAMP] Starting dive-analyser diagnostics..." | tee -a "$LOGFILE"

# Function to check service health
check_service_health() {
    local service=$1
    local container_name="dive-analyser-$service"
    
    if docker ps | grep -q "$container_name"; then
        local status=$(docker ps --format "{{.Status}}" --filter "name=$container_name")
        if [[ $status == *"Up"* ]]; then
            echo -e "${GREEN}✓ $service is UP${NC} ($status)"
            return 0
        else
            echo -e "${RED}✗ $service is NOT UP${NC} ($status)"
            return 1
        fi
    else
        echo -e "${RED}✗ $service container not found${NC}"
        return 1
    fi
}

# Function to check backend API health
check_backend_api() {
    echo ""
    echo "=== Backend API Health Check ==="
    
    local response=$(curl -s -w "\n%{http_code}" http://localhost:6002/api/v1/health 2>&1)
    local body=$(echo "$response" | head -n -1)
    local http_code=$(echo "$response" | tail -n 1)
    
    if [[ $http_code == "200" ]]; then
        echo -e "${GREEN}✓ API is responding (200 OK)${NC}"
        echo "Response: $body" >> "$LOGFILE"
        return 0
    else
        echo -e "${RED}✗ API returned HTTP $http_code${NC}"
        echo "Response: $body" >> "$ERRORFILE"
        return 1
    fi
}

# Function to check nginx proxy
check_nginx_proxy() {
    echo ""
    echo "=== Nginx Proxy Health Check ==="
    
    local response=$(curl -s -w "\n%{http_code}" http://localhost:6090/api/v1/health 2>&1)
    local http_code=$(echo "$response" | tail -n 1)
    
    if [[ $http_code == "200" ]]; then
        echo -e "${GREEN}✓ Nginx is proxying correctly (200 OK)${NC}"
        return 0
    else
        echo -e "${RED}✗ Nginx returned HTTP $http_code${NC}"
        echo "[$TIMESTAMP] Nginx error: HTTP $http_code" >> "$ERRORFILE"
        
        # Check nginx logs for 502 errors
        echo "Recent nginx errors:"
        docker logs dive-analyser-nginx-1 2>&1 | grep -E "\[error\]|502|connection refused" | tail -5
        return 1
    fi
}

# Function to check backend logs for errors
check_backend_logs() {
    echo ""
    echo "=== Backend Log Check ==="
    
    local error_count=$(docker logs dive-analyser-backend-1 2>&1 | grep -c "Error\|PermissionError\|Exception" || true)
    
    if [[ $error_count -gt 0 ]]; then
        echo -e "${YELLOW}⚠ Found $error_count error(s) in backend logs${NC}"
        echo "Recent backend errors:"
        docker logs dive-analyser-backend-1 2>&1 | grep -E "Error|PermissionError|Exception" | tail -3
        
        # Check for permission errors specifically
        if docker logs dive-analyser-backend-1 2>&1 | grep -q "PermissionError"; then
            echo -e "${RED}✗ PERMISSION ERROR DETECTED - Fixing file permissions...${NC}"
            fix_permissions
        fi
        return 1
    else
        echo -e "${GREEN}✓ No errors in backend logs${NC}"
        return 0
    fi
}

# Function to fix permissions
fix_permissions() {
    echo "Fixing file permissions..."
    cd /home/mcauchy/dive-analyser
    
    # Fix logs, media, reports directories
    chmod -R 777 logs media reports 2>/dev/null || true
    mkdir -p logs/audit
    
    echo "Restarting backend with fixed permissions..."
    docker-compose restart backend
    sleep 10
    
    echo -e "${GREEN}✓ Permissions fixed and backend restarted${NC}"
}

# Function to diagnose 502 errors
diagnose_502_errors() {
    echo ""
    echo "=== 502 Bad Gateway Diagnosis ==="
    
    local nginx_errors=$(docker logs dive-analyser-nginx-1 2>&1 | grep -c "502\|connection refused" || true)
    
    if [[ $nginx_errors -gt 0 ]]; then
        echo -e "${RED}✗ Found $nginx_errors instances of 502 errors${NC}"
        
        # Get the upstream error details
        echo "Upstream connection issues:"
        docker logs dive-analyser-nginx-1 2>&1 | grep "upstream:" | tail -1
        
        echo ""
        echo "Diagnostic steps to try:"
        echo "1. Check backend container status: docker ps | grep backend"
        echo "2. Check backend logs: docker logs dive-analyser-backend-1 --tail 20"
        echo "3. Test backend directly: curl http://localhost:6002/api/v1/health"
        echo "4. Verify network: docker network inspect dive-analyser_default"
        
        return 1
    else
        echo -e "${GREEN}✓ No 502 errors detected${NC}"
        return 0
    fi
}

# Main diagnostics loop
echo ""
echo "=== Container Status ==="
check_service_health "backend"
check_service_health "frontend"
check_service_health "nginx"
check_service_health "postgres"
check_service_health "adminer"

check_backend_api
check_nginx_proxy
check_backend_logs
diagnose_502_errors

echo ""
echo "=== Summary ==="
echo "Logs written to: $LOGFILE"
echo "Errors logged to: $ERRORFILE"
echo "[$TIMESTAMP] Diagnostics complete"

# Return 0 if all checks passed, 1 if any failed
exit $?
