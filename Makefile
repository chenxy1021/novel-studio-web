.PHONY: dev start open stop status restart api web test test-store install build

dev start:
	./scripts/dev.sh

open:
	./scripts/dev.sh open

stop:
	./scripts/dev.sh stop

status:
	./scripts/dev.sh status

restart:
	./scripts/dev.sh restart

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
