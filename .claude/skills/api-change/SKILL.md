---
name: api-change
description: Steps for any change to fastgtp's HTTP API, such as a new route, a changed field, status code or error. Use before writing route code.
---

# Change the HTTP API

1. Read `docs/api-guidelines.md`. When a rule there is not clear, read the linked Zalando rule.
2. Write the change in the API spec (`openapi.yaml`) before any code: paths, request and response schemas, status codes, and problem types.
3. If `.spectral.yaml` exists, lint the spec: `npx @stoplight/spectral-cli lint openapi.yaml`. Fix every error.
4. Show the spec change to the owner and wait for agreement. Do not answer a design question with code.
5. Implement the routes to match the spec. Field names, status codes and error bodies must be the same as in the spec.
6. For a new problem type, add a section to `docs/problems.md` and point its `type` URI there.
7. Add tests for each new status code and error, not only the success path.
8. Check that the app's generated OpenAPI (`/openapi.json`) matches the spec.

If a change needs a rule from the "Rules we skip" table, or breaks a rule we follow, ask the owner. If they agree, update `docs/api-guidelines.md` in the same pull request.
