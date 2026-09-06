# No install step required: every target runs from a clean checkout.
PY ?= python3
RUN := PYTHONPATH=src $(PY) -m recon.cli
CASES ?= 500
SEED ?= 7

.PHONY: help run dashboard queue review promote evaluate export test cov lint fmt check clean

help:  ## show this help
	@grep -E '^[a-z-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-12s\033[0m %s\n", $$1, $$2}'

run:  ## the whole loop, before and after learning
	@$(RUN) run --cases $(CASES) --seed $(SEED)

dashboard:  ## write reports/dashboard.html
	@$(RUN) dashboard --cases $(CASES) --seed $(SEED) --out reports/dashboard.html

queue:  ## what still needs a person, and why
	@$(RUN) queue --cases $(CASES) --seed $(SEED)

review:  ## walk the queue and record decisions
	@$(RUN) review --cases $(CASES) --seed $(SEED)

promote:  ## turn confirmed decisions into rules
	@$(RUN) promote --cases $(CASES) --seed $(SEED)

evaluate:  ## score the deterministic matcher alone
	@$(RUN) evaluate --cases $(CASES) --seed $(SEED)

export:  ## write the generated period out as CSV
	@$(RUN) export --cases $(CASES) --seed $(SEED) --out data

test:  ## run the test suite
	@PYTHONPATH=src $(PY) -m pytest

cov:  ## run tests with coverage, enforcing the floor
	@PYTHONPATH=src $(PY) -m pytest --cov=recon --cov-report=term-missing

lint:  ## static checks
	@$(PY) -m ruff check src tests
	@$(PY) -m ruff format --check src tests

fmt:  ## apply formatting
	@$(PY) -m ruff check --fix src tests
	@$(PY) -m ruff format src tests

check: lint cov  ## everything CI runs

clean:  ## remove generated artefacts
	@rm -rf data/*.csv reports/*.html .pytest_cache .coverage htmlcov
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +
