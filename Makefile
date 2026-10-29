SHELL := /bin/bash
MAKEFLAGS += --no-print-directory

LIBRARY_JSON := griptape-nodes-library.json

.PHONY: version/get
version/get: ## Get version.
	@jq -r '.metadata.library_version' $(LIBRARY_JSON)

.PHONY: version/set
version/set: changelog/assert-committed ## Set version. Usage: make version/set v=1.2.3
	@jq --arg v "$(v)" '.metadata.library_version = $$v' $(LIBRARY_JSON) > $(LIBRARY_JSON).tmp
	@mv $(LIBRARY_JSON).tmp $(LIBRARY_JSON)
	@$(MAKE) version/commit

.PHONY: version/patch
version/patch: changelog/assert-committed ## Bump patch version.
	@CURRENT=$$($(MAKE) version/get); \
	IFS='.' read -r major minor patch <<< "$$CURRENT"; \
	NEW_VERSION="$${major}.$${minor}.$$((patch + 1))"; \
	jq --arg v "$$NEW_VERSION" '.metadata.library_version = $$v' $(LIBRARY_JSON) > $(LIBRARY_JSON).tmp; \
	mv $(LIBRARY_JSON).tmp $(LIBRARY_JSON); \
	echo "Bumped to $$NEW_VERSION"
	@$(MAKE) version/commit

.PHONY: version/minor
version/minor: changelog/assert-committed ## Bump minor version.
	@CURRENT=$$($(MAKE) version/get); \
	IFS='.' read -r major minor patch <<< "$$CURRENT"; \
	NEW_VERSION="$${major}.$$((minor + 1)).0"; \
	jq --arg v "$$NEW_VERSION" '.metadata.library_version = $$v' $(LIBRARY_JSON) > $(LIBRARY_JSON).tmp; \
	mv $(LIBRARY_JSON).tmp $(LIBRARY_JSON); \
	echo "Bumped to $$NEW_VERSION"
	@$(MAKE) version/commit

.PHONY: version/major
version/major: changelog/assert-committed ## Bump major version.
	@CURRENT=$$($(MAKE) version/get); \
	IFS='.' read -r major minor patch <<< "$$CURRENT"; \
	NEW_VERSION="$$((major + 1)).0.0"; \
	jq --arg v "$$NEW_VERSION" '.metadata.library_version = $$v' $(LIBRARY_JSON) > $(LIBRARY_JSON).tmp; \
	mv $(LIBRARY_JSON).tmp $(LIBRARY_JSON); \
	echo "Bumped to $$NEW_VERSION"
	@$(MAKE) version/commit

.PHONY: version/commit
version/commit: ## Roll the changelog into the version, then commit both.
	@uv run --no-project python scripts/changelog.py roll $$($(MAKE) version/get) --allow-empty
	@git commit -m "chore: bump v$$($(MAKE) version/get)" -- $(LIBRARY_JSON) CHANGELOG.md changelog.d

# The roll overwrites CHANGELOG.md and deletes the entry files, and the bump commits whatever it left,
# so an entry still being written would ship half-finished or be lost. The library JSON is covered too:
# a bump whose roll failed leaves the new version there, and bumping again from it skips a version.
.PHONY: changelog/assert-committed
changelog/assert-committed:
	@git diff --quiet HEAD -- $(LIBRARY_JSON) CHANGELOG.md changelog.d \
		&& test -z "$$(git ls-files --others --exclude-standard -- changelog.d)" \
		|| { echo "$(LIBRARY_JSON), CHANGELOG.md, or changelog.d holds changes that are not committed."; \
			echo "Commit or stash them first. If a version bump stopped partway, undo it with:"; \
			echo "  git restore $(LIBRARY_JSON) CHANGELOG.md changelog.d"; exit 1; }

.PHONY: version/publish
version/publish: ## Create and push git tags.
	@git fetch --tags --force
	@git tag "v$$(make version/get)"
	@git tag stable -f
	@git push origin "v$$(make version/get)"
	@git push -f origin stable

.PHONY: deps/sync
deps/sync: ## Sync pip_dependencies in the library JSON from pyproject.toml.
	@uv run python -c "\
import tomllib, json; \
pyproject = tomllib.load(open('pyproject.toml', 'rb')); \
deps = [d for d in pyproject['project']['dependencies'] if not d.startswith('griptape-nodes')]; \
lib = json.load(open('$(LIBRARY_JSON)')); \
lib['metadata'].setdefault('dependencies', {})['pip_dependencies'] = deps; \
open('$(LIBRARY_JSON)', 'w').write(json.dumps(lib, indent=4) + '\n'); \
print(f'Synced {len(deps)} dependencies to $(LIBRARY_JSON)')"

.PHONY: install
install: ## Install all dependencies.
	@$(MAKE) install/all

.PHONY: install/core
install/core: deps/sync ## Install core dependencies.
	@uv sync

.PHONY: install/all
install/all: deps/sync ## Install all dependencies.
	@uv sync --all-groups --all-extras

.PHONY: install/dev
install/dev: ## Install dev dependencies.
	@uv sync --group dev

.PHONY: lint
lint: ## Lint project.
	@uv run ruff check --fix

.PHONY: format
format: ## Format project.
	@uv run ruff format

.PHONY: fix
fix: ## Fix project.
	@$(MAKE) format
	@uv run ruff check --fix --unsafe-fixes

.PHONY: test
test: ## Run tests.
	@uv run pytest

.PHONY: test/unit
test/unit: ## Run unit tests.
	@uv run pytest tests/unit

.PHONY: test/integration
test/integration: ## Run integration tests. Nuke-gated tests skip cleanly if NUKE_EXECUTABLE is unset.
	@uv run pytest tests/integration

.PHONY: test/integration/host-api
test/integration/host-api: ## Smoke the host API against a running engine (needs local_socket enabled).
	@uv run pytest tests/integration/test_host_api.py -v -rs

.PHONY: check
check: check/format check/lint check/types check/json check/changelog ## Run all checks.

.PHONY: check/format
check/format:
	@uv run ruff format --check

.PHONY: check/lint
check/lint:
	@uv run ruff check .

.PHONY: check/types
check/types:
	@uv run pyright .

.PHONY: check/json
check/json: ## Validate JSON files.
	@echo "Checking JSON files..."
	@find . -name "*.json" -type f \
		! -path "./.venv/*" \
		! -path "./node_modules/*" \
		-exec sh -c 'jq empty "{}" > /dev/null 2>&1 || (echo "Invalid JSON: {}" && exit 1)' \;

.PHONY: check/changelog
check/changelog: ## Check CHANGELOG.md and the changelog.d entries follow Keep a Changelog.
	@uv run --no-project python scripts/changelog.py check

.PHONY: changelog
changelog: ## Print [Unreleased] as the next version will show it, changelog.d entries folded in.
	@uv run --no-project python scripts/changelog.py render

.DEFAULT_GOAL := help
.PHONY: help
help: ## Print Makefile help text.
	@# Matches targets with a comment in the format <target>: ## <comment>
	@# then formats help output using these values.
	@grep -E '^[a-zA-Z_\/-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	| awk 'BEGIN {FS = ":.*?## "}; \
		{printf "\033[36m%-12s\033[0m%s\n", $$1, $$2}'
