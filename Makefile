.PHONY: dev api web test test-store install build

dev:
	./scripts/dev.sh

api:
	cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8010 --reload

web:
	cd frontend && npm run dev

test:
	cd backend && uv run pytest tests/ -q
	cd frontend && npm test

test-store:
	cd frontend && npm test

install:
	cd backend && uv sync
	cd frontend && npm install

build:
	cd frontend && npm run build
