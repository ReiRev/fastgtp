# fastgtp

fastgtp wraps a Go Text Protocol (GTP) engine process in a FastAPI service.

## Layout

- `fastgtp/server/transport.py`: runs the engine process and sends it GTP commands.
- `fastgtp/server/gtp.py`: GTP replies and errors.
- `fastgtp/server/router.py`: the HTTP routes.
- `fastgtp/server/main.py`: builds the app from environment variables.
- `tests/`: pytest tests. `tests/transport/stub_engine.py` is a small fake engine.

## Commands

```bash
poetry install                      # set up .venv
.venv/bin/pytest -q -k "gnugo or transport"
uvx black --check <changed files>
```

The tests run against GNU Go and KataGo. KataGo needs `/opt/katago` from the dev container. Outside it, deselect KataGo with `-k "gnugo or ..."`.

## Rules

- **Public repository.** Do not write host names, IP addresses, home directory paths, people's names or details of anyone's servers or network in code, commits, issues or pull requests.
- **HTTP API.** Follow `docs/api-guidelines.md`. Change the API spec first and get it agreed before writing code.
- **Ask first.** Ask the owner before you open an issue or a pull request.
- **Small pull requests.** Keep each pull request under about 400 added lines. Split larger work into stacked pull requests.
- **Review.** Before opening a pull request, have the `reviewer` agent review the diff. Fix every HIGH and MEDIUM finding. Stop after two review rounds and report what is left.
- **Engines in tests.** Use GNU Go or a fake engine from `tests/`. Do not use the GPU or start KataGo outside the dev container.
- **Comments** explain why, not what. Write comments, docs and pull request text in plain English.
- **Formatting.** Format Python with black.

For a pull request, follow the `open-pr` skill. For a change to the HTTP API, follow the `api-change` skill.
