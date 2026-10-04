# Development Guide

Local development setup and workflows.

---

## Quick Start

### Backend Development

```bash
# Setup
cd backend
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Start database
docker-compose up postgres -d

# Run migrations
alembic upgrade head

# Start dev server
uvicorn app.main:app --reload --port 8000
```

### Frontend Development

```bash
# Setup
cd frontend
npm install

# Start dev server
npm run dev
```

Access: `http://localhost:6001`

---

## Testing

### Backend Tests

```bash
# All tests
pytest tests/ -v

# With coverage
pytest tests/ --cov=app --cov-report=html

# Specific test
pytest tests/test_milestones.py::test_breakthrough_detection -v

# Watch mode
ptw tests/
```

### Frontend Tests

```bash
# Unit tests
npm test

# E2E tests
npm run test:e2e

# Watch mode
npm test -- --watch
```

---

## Code Quality

### Python

```bash
# Format
black backend/
isort backend/

# Lint
flake8 backend/
mypy backend/
```

### TypeScript

```bash
# Format
npm run format

# Lint
npm run lint
```

---

## Database

### Migrations

```bash
# Create migration
alembic revision --autogenerate -m "add phase columns"

# Apply migrations
alembic upgrade head

# Rollback
alembic downgrade -1

# View history
alembic history
```

### SQL Console

```bash
# Via Docker
docker-compose exec postgres psql -U diving diving_analyzer_db

# Direct connection
psql postgresql://diving:REDACTED-CREDENTIAL@localhost:6432/diving_analyzer_db
```

---

## Debugging

### Backend

```python
# Add breakpoint
import pdb; pdb.set_trace()

# Or with ipdb
import ipdb; ipdb.set_trace()
```

### Frontend

```typescript
// Browser DevTools
debugger;

// Console logging
console.log('Debug:', data);
```

---

## Project Structure

```
diving-analyser/
├── backend/
│   ├── app/
│   │   ├── api/v1/          # API endpoints
│   │   ├── models/          # Database models
│   │   ├── schemas/         # Pydantic schemas
│   │   ├── services/        # Business logic
│   │   └── main.py          # FastAPI app
│   ├── tests/               # Backend tests
│   ├── migrations/          # Alembic migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/      # React components
│   │   ├── pages/           # Page components
│   │   ├── hooks/           # Custom hooks
│   │   ├── services/        # API clients
│   │   └── main.tsx         # Entry point
│   ├── e2e/                 # Playwright tests
│   └── package.json
├── mac-agent/
│   ├── src/                 # Mac agent source
│   ├── tests/               # Agent tests
│   └── config.yaml
├── docs/                    # Documentation
├── docker-compose.yml       # Docker configuration
└── README.md
```

---

## Contributing Workflow

1. Create feature branch: `git checkout -b feature/my-feature`
2. Make changes
3. Run tests: `pytest` & `npm test`
4. Format code: `black` & `npm run format`
5. Commit: `git commit -m "feat: add feature"`
6. Push: `git push origin feature/my-feature`
7. Create Pull Request

See [CONTRIBUTING.md](../CONTRIBUTING.md) for full guidelines.

---

## Useful Commands

### Docker

```bash
# Rebuild single service
docker-compose build backend

# View logs
docker-compose logs -f backend

# Shell into container
docker-compose exec backend bash

# Remove all containers
docker-compose down -v
```

### Git

```bash
# Sync with upstream
git fetch upstream
git rebase upstream/main

# Interactive rebase
git rebase -i HEAD~3

# Stash changes
git stash
git stash pop
```

---

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design details.
