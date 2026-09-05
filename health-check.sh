#!/bin/bash
# dive-analyser Quick Health Check
# Shows essential status at a glance

set -e
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

cd /home/mcauchy/dive-analyser

echo "=== DIVE-ANALYSER HEALTH CHECK ==="
echo ""

# Check all containers
echo "🐳 Container Status:"
docker ps --filter "name=dive-analyser" --format "{{.Names}}\t{{.Status}}" | while read name status; do
  if [[ $status == *"Up"* ]]; then
    echo -e "  ${GREEN}✓${NC} $name: $status"
  else
    echo -e "  ${RED}✗${NC} $name: $status"
  fi
done

echo ""

# Test backend API
echo "🔧 Backend API Health:"
if response=$(curl -s -w "\n%{http_code}" http://localhost:6002/api/v1/health 2>&1); then
  http_code=$(echo "$response" | tail -n 1)
  if [[ $http_code == "200" ]]; then
    echo -e "  ${GREEN}✓${NC} Backend responding (200 OK)"
  else
    echo -e "  ${RED}✗${NC} Backend returned HTTP $http_code"
  fi
else
  echo -e "  ${RED}✗${NC} Backend unreachable"
fi

echo ""

# Test nginx proxy
echo "🌐 Nginx Proxy Health:"
if response=$(curl -s -w "\n%{http_code}" http://localhost:6090/api/v1/health 2>&1); then
  http_code=$(echo "$response" | tail -n 1)
  if [[ $http_code == "200" ]]; then
    echo -e "  ${GREEN}✓${NC} Nginx proxying correctly (200 OK)"
  else
    echo -e "  ${RED}✗${NC} Nginx returned HTTP $http_code"
  fi
else
  echo -e "  ${RED}✗${NC} Nginx unreachable"
fi

echo ""

# Check for critical errors in logs
echo "📋 Recent Errors:"
error_count=$(docker logs dive-analyser-backend-1 2>&1 | grep -c "ERROR\|PermissionError\|FATAL" || echo "0")
if [[ $error_count -gt 0 ]]; then
  echo -e "  ${RED}⚠ Found $error_count error(s) in backend${NC}"
  docker logs dive-analyser-backend-1 2>&1 | grep -E "ERROR|PermissionError|FATAL" | tail -2 | sed 's/^/    /'
else
  echo -e "  ${GREEN}✓${NC} No critical errors"
fi

echo ""
echo "=== ACCESS POINTS ==="
echo "  Frontend:  http://192.168.1.57:6090/"
echo "  API:       http://localhost:6002/api/v1/"
echo "  Database:  http://localhost:8080/ (adminer)"
echo ""
