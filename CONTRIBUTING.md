# Contributing

## Development Setup

This project uses [uv](https://docs.astral.sh/uv/) for dependency management. Install dev dependencies with:

```bash
make install/dev
```

To install all dependencies including core and extras:

```bash
make install
```

## Makefile Targets

Run `make` with no arguments to see all available targets.

### Checks

Run all checks (format, lint, types) before submitting a PR:

```bash
make check
```

Individual checks:

```bash
make check/format   # ruff format --check
make check/lint     # ruff check
make check/types    # pyright
make check/json     # validate JSON files with jq
```

### Fixing Issues

Auto-fix formatting and linting issues:

```bash
make fix
```

### Dependency Sync

The `pip_dependencies` field in the library JSON is kept in sync with `pyproject.toml`. Run this after adding or removing dependencies:

```bash
make deps/sync
```

This is also run automatically as part of `make install/core` and `make install/all`.

## CI

The CI workflow runs `make check` on every pull request and push to `main`. PRs must pass all checks before merging.

## Releases

Library versions follow [semantic versioning](https://semver.org/). The version is stored in the library JSON file under `metadata.library_version`.

To check the current version:

```bash
make version/get
```

To set a specific version:

```bash
make version/set v=1.2.3
```

### Regular Release

1. Merge your changes to `main`.

2. Run **Actions > Version Bump (Patch)** or **Actions > Version Bump (Minor)** on `main`. This increments the version in the library JSON and commits the change.

   Or bump locally and push:

   ```bash
   make version/patch   # 1.2.3 → 1.2.4
   make version/minor   # 1.2.3 → 1.3.0
   make version/major   # 1.2.3 → 2.0.0
   ```

3. Run **Actions > Version Publish** on `main`. This creates and pushes the version tag (e.g. `v1.2.3`), updates the `stable` tag, and creates a GitHub release with auto-generated release notes.

### Patch Release

To release a fix without including all commits on `main`, use a release branch:

1. Create a branch from the tag you want to patch:

   ```bash
   git checkout -b release/v0.50 v0.50.0
   git push -u origin release/v0.50
   ```

2. Cherry-pick the fix commit(s) you want to include:

   ```bash
   git cherry-pick <commit-sha>
   git push
   ```

3. Run **Actions > Version Bump (Patch)** and set the branch to `release/v0.50`.

4. Run **Actions > Version Publish** and set the branch to `release/v0.50`.
