.PHONY: install-dev up down reset test smoke migrate seed lint

install-dev:
	pip install -e .[dev]

up:
	docker compose up --build

down:
	docker compose down --remove-orphans

reset:
	docker compose down -v --remove-orphans

test:
	pytest -q tests/unit tests/integration

smoke:
	SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q

migrate:
	docker compose run --rm api alembic upgrade head

seed:
	docker compose run --rm api python scripts/seed_demo_data.py

lint:
	ruff check .
