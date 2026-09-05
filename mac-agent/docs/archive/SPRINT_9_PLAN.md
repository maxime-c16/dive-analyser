# Sprint 9: Production & Deployment - Plan

**Status**: IN PROGRESS
**Target Date**: Jan 31, 2026
**Tasks**: 8 (63-70)
**Deployment Target**: 192.168.1.57

## Sprint Overview

Sprint 9 delivers production hardening, deployment automation, monitoring setup, and full production rollout. System moves from development to production with comprehensive safety measures.

## Tasks Breakdown

### Task 63: Security Hardening & Validation
**Objective**: Harden backend and frontend against common vulnerabilities
**Deliverables**:
- Input validation and sanitization
- CORS hardening
- Rate limiting refinement
- SQL injection prevention
- XSS protection
- CSRF tokens
- Security headers
- API authentication

**Files to Create**:
- `backend/app/security/validators.py` - Input validation
- `backend/app/security/cors.py` - CORS configuration
- `backend/app/middleware/security.py` - Security headers
- `frontend/src/security/api-validation.ts` - Frontend validation

**Metrics**:
- 0 security vulnerabilities (OWASP Top 10)
- All endpoints validated
- Rate limits enforced
- Auth tokens present

### Task 64: Documentation Completeness
**Objective**: Complete all user-facing and operational documentation
**Deliverables**:
- User guide (Journey feature, Analytics, etc.)
- API documentation (OpenAPI/Swagger)
- Operational runbook
- Troubleshooting guide
- FAQ document
- Installation guide updates
- Deployment checklist

**Files to Create**:
- `docs/USER_GUIDE.md` - Complete user documentation
- `docs/API_REFERENCE.md` - API documentation
- `docs/OPERATIONAL_RUNBOOK.md` - Operational procedures
- `docs/TROUBLESHOOTING.md` - Common issues
- `docs/FAQ.md` - Frequently asked questions

**Metrics**:
- 100% API endpoints documented
- User guide covers all features
- Common errors addressed
- Setup time <30 minutes

### Task 65: Feature Flags & Canary Deployment Setup
**Objective**: Implement feature flags for controlled rollout
**Deliverables**:
- Feature flag service
- A/B testing capability
- Gradual rollout mechanism
- Toggle system for features
- Analytics per flag
- Flag management UI

**Files to Create**:
- `backend/app/services/feature_flags.py` - Feature flag service
- `backend/app/api/v1/feature_flags.py` - API endpoints
- `frontend/src/services/featureFlags.ts` - Frontend integration

**Feature Flags**:
- `sync_enabled`: Enable/disable video sync
- `journey_analytics`: Enable/disable journey analytics
- `milestone_notifications`: Enable/disable milestone alerts
- `two_phase_scoring`: Enable/disable two-phase dive format
- `canary_mode`: Test mode for new features

### Task 66: Gradual Rollout Plan Execution
**Objective**: Execute phased rollout to production
**Deliverables**:
- Phased deployment schedule
- Rollout monitoring
- Metrics validation at each phase
- Rollback procedures

**Phases**:
1. **Phase 1 (Day 1)**: 5% traffic - Core features only
2. **Phase 2 (Day 2)**: 25% traffic - Add sync features
3. **Phase 3 (Day 3)**: 50% traffic - All features
4. **Phase 4 (Day 4+)**: 100% production traffic

### Task 67: Monitoring & Alerting Setup
**Objective**: Production monitoring and alert system
**Deliverables**:
- Prometheus metrics collection
- Grafana dashboards
- Alert rules and thresholds
- Log aggregation
- Performance monitoring
- Error tracking

**Metrics to Monitor**:
- API response time (p50, p95, p99)
- WebSocket connection count
- Sync success rate
- Error rates
- Database query time
- Frontend performance
- Memory usage
- CPU usage

### Task 68: Production Deployment to 192.168.1.57
**Objective**: Deploy to production server
**Deliverables**:
- Deploy backend service
- Deploy frontend application
- Configure environment
- Run migrations
- Seed data if needed
- Verify health checks

### Task 69: Post-Deployment Validation (24 hours)
**Objective**: Validate deployment success over 24-hour period
**Deliverables**:
- Health check monitoring
- User acceptance testing
- Performance validation
- Security scanning
- Data integrity verification

### Task 70: Team Handoff & Documentation
**Objective**: Complete documentation for operational team
**Deliverables**:
- Runbook for on-call team
- Training documentation
- Contact procedures
- Emergency procedures
- Regular maintenance tasks

## Detailed Implementation

### Security Hardening (Task 63)

```python
# backend/app/security/validators.py
class InputValidator:
    @staticmethod
    def validate_dive_code(code: str) -> bool:
        # Only 3-4 digits + position letter
        return bool(re.match(r'^\d{3,4}[A-D]?$', code))

    @staticmethod
    def validate_height(height: str) -> bool:
        # Only 1m, 3m, 5m, 7m, 10m, with optional P
        valid = ['1m', '3m', '5m', '7m', '10m']
        return height.lower() in valid or height.lower() in [f"{v}p" for v in valid]

    @staticmethod
    def sanitize_text(text: str) -> str:
        # Remove dangerous HTML/JS
        return bleach.clean(text, tags=[], strip=True)

# Rate limiting
RATE_LIMITS = {
    '/api/v1/sync/batch': '10/minute',
    '/api/v1/ws/sync': '100/minute',
    '/api/v1/journey/journey': '30/minute',
}

# Security headers
SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'X-XSS-Protection': '1; mode=block',
    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
    'Content-Security-Policy': "default-src 'self'",
}
```

### Documentation (Task 64)

```markdown
# USER_GUIDE.md

## Getting Started

### Accessing the Application
- Navigate to http://192.168.1.57
- No login required (local network only)

### Your Journey Page
- View complete diving progression
- See all milestones unlocked
- Track performance over time

### Analytics Dashboard
- Monthly progression charts
- Performance by height breakdown
- Success rate trending

### Live Sync Status
- Real-time video sync from Photos
- Progress indicator
- Milestone notifications

## Common Tasks

### Viewing Milestones
1. Navigate to "Your Journey" → "Milestones"
2. Filter by significance level
3. Click milestone to see details

### Understanding Two-Phase Format
- Phase 1: Hurdle + Flight (Takeoff)
- Phase 2: Opening + Entry (Landing)

...
```

### Feature Flags (Task 65)

```python
# backend/app/services/feature_flags.py
class FeatureFlagService:
    def __init__(self):
        self.flags = {
            'sync_enabled': {'enabled': True, 'rollout': 100},
            'journey_analytics': {'enabled': True, 'rollout': 100},
            'milestone_notifications': {'enabled': True, 'rollout': 100},
            'two_phase_scoring': {'enabled': True, 'rollout': 100},
            'canary_mode': {'enabled': False, 'rollout': 0},
        }

    def is_enabled(self, flag_name: str, user_id: str = None) -> bool:
        flag = self.flags.get(flag_name)
        if not flag:
            return False

        # Check rollout percentage
        if user_id:
            # Hash user ID to rollout percentage
            hash_val = hash(f"{flag_name}_{user_id}") % 100
            return hash_val < flag['rollout']

        return flag['enabled']
```

### Monitoring Setup (Task 67)

```yaml
# prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'diving-analyser'
    static_configs:
      - targets: ['192.168.1.57:8000']

  - job_name: 'postgres'
    static_configs:
      - targets: ['192.168.1.57:9187']

# Alert rules
groups:
  - name: diving_analyser
    rules:
      - alert: HighErrorRate
        expr: rate(errors_total[5m]) > 0.05
        for: 5m

      - alert: SlowResponse
        expr: histogram_quantile(0.95, response_time_seconds) > 1.0
        for: 5m

      - alert: LowDiskSpace
        expr: disk_free_bytes / disk_total_bytes < 0.1
```

## Deployment Checklist

### Pre-Deployment (Day 0)
- [ ] Run all tests (50+ tests passing)
- [ ] Security audit complete
- [ ] Performance benchmarks met
- [ ] Backups created
- [ ] Rollback procedure tested
- [ ] Team trained

### Deployment (Day 1)
- [ ] Backup database
- [ ] Deploy backend service
- [ ] Run database migrations
- [ ] Deploy frontend application
- [ ] Configure environment variables
- [ ] Verify health checks
- [ ] Test critical flows

### Post-Deployment (Day 1-4)
- [ ] Monitor metrics for 24 hours
- [ ] Check error logs
- [ ] Validate data integrity
- [ ] Perform user acceptance testing
- [ ] Adjust rollout percentage daily
- [ ] Document any issues

### Metrics to Track

**Day 1**: 5% traffic
```
Target:
  - Error rate: < 0.1%
  - Response time p95: < 500ms
  - Sync success: > 99%
```

**Day 2**: 25% traffic
```
Target:
  - Error rate: < 0.05%
  - Response time p95: < 400ms
  - Sync success: > 99.5%
```

**Day 3**: 50% traffic
```
Target:
  - Error rate: < 0.05%
  - Response time p95: < 400ms
  - Sync success: > 99.5%
  - Zero data issues
```

**Day 4+**: 100% traffic
```
Target:
  - Error rate: < 0.05%
  - Response time p95: < 400ms
  - Sync success: > 99.5%
  - Zero security incidents
```

## Risk Mitigation

### Potential Issues & Mitigations

| Issue | Probability | Impact | Mitigation |
|-------|-----------|--------|-----------|
| High traffic surge | Low | High | Auto-scaling, rate limits |
| Database overload | Medium | High | Caching, query optimization |
| WebSocket disconnect | Low | Medium | Auto-reconnect (built-in) |
| Data corruption | Very Low | Critical | Backups, validation tests |
| Security breach | Very Low | Critical | Security audit, headers |

## Success Criteria

All must be met to proceed:
- [ ] 50+ automated tests passing
- [ ] 0 critical security issues
- [ ] <100ms p95 latency
- [ ] 99.5%+ availability
- [ ] 100% data integrity
- [ ] Full documentation
- [ ] Team training complete
- [ ] Rollback tested

## Timeline

**Day 1**: Security hardening & docs
**Day 2**: Feature flags & monitoring setup
**Day 3**: Deploy to production (5% traffic)
**Day 4**: Increase to 25% traffic
**Day 5**: Increase to 50% traffic
**Day 6+**: Full production (100% traffic)

## Team Responsibilities

**DevOps**: Deployment, monitoring, infrastructure
**Engineering**: Feature flags, documentation
**QA**: Validation testing, monitoring
**On-Call**: 24/7 support during rollout

## Success Indicators

- [x] All code complete and tested
- [ ] Security audit passed
- [ ] Documentation complete
- [ ] Monitoring configured
- [ ] Team trained and ready
- [ ] First 24 hours successful
- [ ] Full rollout complete

---

**Sprint 9 Ready**: All planning complete, execution begins now.
