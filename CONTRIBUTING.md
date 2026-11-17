# Contributing to piclas-db

## Development

```bash
python -m pip install -e ".[dev]"
prek install          # pre-commit hooks: ruff, ty, vulture, gitleaks, file checks
pytest                # tests use synthetic data only
```

Never commit data: databases, original downloads, extracted or exported tables and plots stay in the local store or the private
source repository (see `.gitignore`). Test fixtures are synthetic.

## Versioning

piclas-db uses 0.x.0 versions until the tool is feature complete; the minor version is incremented with every development step,
fixes within a step increment the patch version (e.g. 0.11.1). Version 1.0.0 marks the first stable release. The version is only
defined in `pyproject.toml`.

## Release checklist

1. Update `version` in `pyproject.toml` and both `version` entries in `CITATION.cff`, and add a section `## <version>` to
   `CHANGELOG.md` (it becomes the release notes).
2. Check locally: `pytest`, `prek run --all-files`, `piclas-db --version`.
3. Commit, push and wait for the CI to pass on `main`.
4. Tag and push the tag:

   ```bash
   git tag -a v<version> -m "piclas-db <version>"
   git push origin v<version>
   ```

5. The release workflow (`.github/workflows/release.yml`) checks that tag, `pyproject.toml`, `CITATION.cff` and `CHANGELOG.md` agree, builds and tests
   the wheel, and creates the GitHub release with the changelog section and the distribution files.
6. Zenodo archives the published release and assigns a version DOI (metadata from `CITATION.cff`). After the first release, add the
   concept DOI (valid for all versions) to `CITATION.cff` and the DOI badge to `README.md`.
7. Optional: publishing to PyPI runs if the repository variable `PUBLISH_PYPI` is `true` and trusted publishing is set up for the
   project `piclas-db` on PyPI (environment `pypi`).
