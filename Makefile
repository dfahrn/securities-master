.PHONY: up down migrate test

up:
	docker compose up -d
	@for i in $$(seq 1 30); do \
		docker compose exec -T postgres pg_isready -U sm -d securities_master && exit 0; \
		echo "waiting for postgres ($$i/30)"; sleep 2; \
	done; \
	echo "postgres did not become ready in 60s"; exit 1

down:
	docker compose down

# Both databases must be migrated: the test database is not a side effect of
# migrating the application one, and `make` does not read .env, so
# TEST_DATABASE_URL has to be sourced explicitly.
migrate:
	uv run alembic upgrade head
	set -a; . ./.env; set +a; DATABASE_URL="$$TEST_DATABASE_URL" uv run alembic upgrade head

test:
	uv run pytest -v
