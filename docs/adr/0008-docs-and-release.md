# ADR 0008: Docs site and release

Date: 2026-11-19.

## Decisions

1. **MkDocs 1.6.1 with Material for MkDocs 9.8.1.** MkDocs itself has had no release since
   August 2024; Material is maintained (9.8.1, November 2026) and its authors' successor,
   Zensical, is at 0.1.2. The build itself announces that Material reaches end of life on
   5 May 2027 (critical fixes until then). The stable pair is used now; move to Zensical,
   which reads the same `mkdocs.yml`, before that date. The site is built with `--strict` in
   CI, so a broken link or missing page fails.
2. **Publishing is the owner's action.** `.github/workflows/release.yml` runs when a `v*` tag
   is pushed: it checks the tag equals the package version, builds once, and publishes with
   PyPI trusted publishing (OpenID Connect, no API token stored in GitHub). The publish job
   uses the `pypi` environment so it can require a manual approval.
3. **Docs deploy is manual** (`docs.yml`, `workflow_dispatch`): GitHub Pages on a private repo
   needs a paid plan, and the site should go live when the repo goes public.
4. **A screenshot, not a recording, at the top of the README.** Making a GIF needs ffmpeg,
   which is not installed and was not downloaded for this.
5. **"Works on a clean machine" is checked in Docker** (`scripts/clean_install_check.py`): the
   built wheel is installed into a fresh `python:3.13-slim` container, the README's quick-start
   app (extracted from the README itself) is run, and the panel is requested.

## Consequences

- Before tagging: run `scripts/clean_install_check.py`, and set up the trusted publisher on
  PyPI (owner, repository `pgsql-loupe`, workflow `release.yml`, environment `pypi`).
