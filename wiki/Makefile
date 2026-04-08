# Grid Tactics Wiki — dev helpers
# Requires: docker, docker compose v2

.PHONY: dev down logs nuke ps status

dev:
	@if [ ! -f .env ]; then cp .env.example .env && echo "Created .env from .env.example"; fi
	docker compose up -d
	@echo "Wiki starting at http://localhost:8080 (wait ~60s for first boot)"

down:
	docker compose down

logs:
	docker compose logs -f mediawiki

nuke:
	@echo "WARNING: this will delete all wiki data volumes (mw_data, db_data, redis_data)."
	@echo "Press Ctrl-C within 5s to abort..."
	@sleep 5
	docker compose down -v

ps status:
	docker compose ps
