.PHONY: up down migrate test

up:
	docker compose up -d
	docker compose exec -T postgres pg_isready -U sm -d securities_master

down:
	docker compose down

migrate:
	uv run alembic upgrade head

test:
	uv run pytest -v
