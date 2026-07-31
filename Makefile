UV_CACHE_DIR ?= /private/tmp/uv-cache
RUN := env -u VIRTUAL_ENV UV_CACHE_DIR=$(UV_CACHE_DIR) uv run
SCENARIO ?= rename_order_placed_at

.PHONY: setup seed verify simulate test lint preflight

setup:
	@echo "Setting up the Python 3.11 environment with uv..."
	@command -v uv >/dev/null 2>&1 || { echo "ERROR: uv is required. Install it from https://docs.astral.sh/uv/ and retry 'make setup'."; exit 1; }
	@env -u VIRTUAL_ENV UV_CACHE_DIR=$(UV_CACHE_DIR) uv sync || { echo "ERROR: dependency sync failed. Check Python 3.11 availability and network access, then retry."; exit 1; }
	@echo "Setup complete. Run 'make seed' to load the ShopFlow catalog."

preflight:
	@echo "Checking that DataHub GMS is reachable..."
	@$(RUN) python -c "from repair_agent.datahub_io.client import DataHubIO; DataHubIO().preflight()" || { echo "ERROR: DataHub preflight failed. DATAHUB_GMS_URL must be the quickstart GMS at host port 8081; port 8080 belongs to an unrelated app. Start DataHub separately or correct the URL, then retry."; exit 1; }

seed: preflight
	@echo "Seeding idempotent ShopFlow metadata into DataHub..."
	@$(RUN) python scripts/seed_datahub.py || { echo "ERROR: seed failed. Review the error above, confirm GMS is on :8081, and retry 'make seed'."; exit 1; }

verify: preflight
	@echo "Verifying ShopFlow schemas and column-level lineage..."
	@$(RUN) python scripts/seed_datahub.py --verify || { echo "ERROR: verification failed. Re-run 'make seed', confirm GMS is on :8081 (not :8080), and retry."; exit 1; }

simulate:
	@echo "Applying drift scenario $(SCENARIO)..."
	@$(RUN) python scripts/simulate_drift.py $(SCENARIO) || { echo "ERROR: drift simulation failed. Check the scenario name and DataHub preflight output, then retry."; exit 1; }

test:
	@echo "Running the Slice A consistency tests..."
	@$(RUN) pytest tests/ -q || { echo "ERROR: tests failed. Fix the reported warehouse/metadata mismatch before continuing."; exit 1; }

lint:
	@echo "Linting the Python source, scripts, and tests..."
	@$(RUN) ruff check src/ scripts/ tests/ || { echo "ERROR: lint failed. Run the printed ruff fixes, then retry 'make lint'."; exit 1; }

