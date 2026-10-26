---
name: api-change
description: Steps for any change to fastgtp's HTTP API, such as a new route, a changed field, status code or error. Use before writing route code.
---

# Change the HTTP API

1. Read `docs/api-guidelines.md`. When a rule there is not clear, read the linked Zalando rule.
2. Write the change in the API spec (`openapi.yaml`) before any code: paths, request and response schemas, status codes, and problem types.
3. If `.spectral.yaml` exists, lint the spec: `npx @stoplight/spectral-cli@6.15.0 lint openapi.yaml`. Fix every error.
4. Show the spec change to the owner and wait for agreement. Do not answer a design question with code.
5. Implement the routes to match the spec. Field names, status codes and error bodies must be the same as in the spec.
6. For a new problem type, add a section to `docs/problems.md` (create the file if it is missing) and point its `type` URI there.
7. Add tests for each new status code and error, not only the success path.
8. The app serves `openapi.yaml` as `/openapi.json`, so the document cannot drift, but the routes can. `tests/server/test_spec.py` checks that the app's routes and methods are the ones the spec lists. When you build a path that is in the spec, remove it from `NOT_YET_BUILT` there.

If a change needs a rule from the "Rules we skip" table, or breaks a rule we follow, ask the owner. If they agree, update `docs/api-guidelines.md` in the same pull request.
