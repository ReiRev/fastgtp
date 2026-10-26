---
name: open-pr
description: Checklist for opening a pull request in fastgtp. Use when a change is ready for a pull request.
---

# Open a pull request

1. Ask the owner before you open it.
2. Branch from `origin/main`.
3. Count the added lines: `git diff --numstat origin/main...HEAD -- . ':!poetry.lock' | awk '{ a += $1 } END { print a }'`. Over about 400, split the change into stacked pull requests.
4. Run the tests for the changed area and `uvx black --check` on the changed Python files.
5. Run the changed behavior, not only the tests. For an HTTP change, start `uvicorn` on a free localhost port and `curl` it. Keep the request and the response for the description.
6. Search the diff and the description for host names, IP addresses, home directory paths, people's names and server or network details. Remove them.
7. Have the `reviewer` agent review the diff. Fix every HIGH and MEDIUM finding and re-run it once. After two rounds, stop and tell the owner what is left.
8. Write the description: what changed, why, the validation you ran with its output, and known limits. Do not describe the review rounds.
9. Write the body to a temporary Markdown file and use `gh pr create --body-file`.
