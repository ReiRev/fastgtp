# API guidelines

fastgtp follows the [Zalando RESTful API Guidelines](https://opensource.zalando.com/restful-api-guidelines/).
This page lists the rules we use, the rules we skip, and how we apply them to GTP.
Each number links to the rule: `https://opensource.zalando.com/restful-api-guidelines/#<number>`.
Read the rule itself when this page is not enough.

CI checks `openapi.yaml` with [Spectral](https://github.com/stoplightio/spectral)
and the [Zalando ruleset](https://github.com/baloise-incubator/spectral-ruleset), with the skipped rules below turned off (`.spectral.yaml`).
Run it locally with `npx @stoplight/spectral-cli@6.15.0 lint openapi.yaml`.

## Rules we follow

### Spec and compatibility

- [#100](https://opensource.zalando.com/restful-api-guidelines/#100), [#101](https://opensource.zalando.com/restful-api-guidelines/#101): Write the change in `openapi.yaml` first. Code comes after the spec is agreed.
- [#103](https://opensource.zalando.com/restful-api-guidelines/#103): U.S. English.
- [#106](https://opensource.zalando.com/restful-api-guidelines/#106), [#107](https://opensource.zalando.com/restful-api-guidelines/#107), [#108](https://opensource.zalando.com/restful-api-guidelines/#108): Do not break clients. Add fields; do not rename or remove them.
- [#113](https://opensource.zalando.com/restful-api-guidelines/#113), [#115](https://opensource.zalando.com/restful-api-guidelines/#115): No version in the URL. Avoid versioning by staying compatible.
- [#116](https://opensource.zalando.com/restful-api-guidelines/#116), [#218](https://opensource.zalando.com/restful-api-guidelines/#218): `info.version` uses semantic versioning.
- [#187](https://opensource.zalando.com/restful-api-guidelines/#187): Mark deprecated operations and fields with `deprecated: true`.

### URLs

- [#134](https://opensource.zalando.com/restful-api-guidelines/#134), [#129](https://opensource.zalando.com/restful-api-guidelines/#129), [#136](https://opensource.zalando.com/restful-api-guidelines/#136): Plural nouns, kebab-case, no trailing slash. For example `/analysis-jobs`.
- [#141](https://opensource.zalando.com/restful-api-guidelines/#141), [#138](https://opensource.zalando.com/restful-api-guidelines/#138): No verbs in URLs. A GTP command becomes a resource (see below).
- [#135](https://opensource.zalando.com/restful-api-guidelines/#135): No `/api` prefix.
- [#143](https://opensource.zalando.com/restful-api-guidelines/#143), [#147](https://opensource.zalando.com/restful-api-guidelines/#147): Sub-resources by path, at most two levels.
- [#130](https://opensource.zalando.com/restful-api-guidelines/#130), [#137](https://opensource.zalando.com/restful-api-guidelines/#137): Query parameters in snake_case, with the usual names (`cursor`, `limit`).

### JSON

- [#118](https://opensource.zalando.com/restful-api-guidelines/#118): Property names in snake_case.
- [#240](https://opensource.zalando.com/restful-api-guidelines/#240): Enum values in UPPER_SNAKE_CASE, for example `BLACK`, `RUNNING`.
- [#110](https://opensource.zalando.com/restful-api-guidelines/#110): The top level of a body is always an object.
- [#120](https://opensource.zalando.com/restful-api-guidelines/#120): Array names are plural.
- [#123](https://opensource.zalando.com/restful-api-guidelines/#123), [#122](https://opensource.zalando.com/restful-api-guidelines/#122), [#124](https://opensource.zalando.com/restful-api-guidelines/#124): `null` and a missing field mean the same thing. Booleans are never `null`. Empty arrays are `[]`.
- [#169](https://opensource.zalando.com/restful-api-guidelines/#169), [#235](https://opensource.zalando.com/restful-api-guidelines/#235): Times are RFC 3339 strings in UTC, named `*_at`.
- [#171](https://opensource.zalando.com/restful-api-guidelines/#171): Every number has a `format` (`int32`, `double`).

### Methods and status codes

- [#148](https://opensource.zalando.com/restful-api-guidelines/#148), [#149](https://opensource.zalando.com/restful-api-guidelines/#149): Use HTTP methods as RFC 9110 defines them.
- [#151](https://opensource.zalando.com/restful-api-guidelines/#151): Every operation lists its success and error responses.
- [#150](https://opensource.zalando.com/restful-api-guidelines/#150), [#220](https://opensource.zalando.com/restful-api-guidelines/#220): Common status codes, and the most specific one.
- [#251](https://opensource.zalando.com/restful-api-guidelines/#251): No redirects.
- When the job queue or the session limit is full, answer `503` with `Retry-After`. `429` is only for a client that breaks a rate limit ([#153](https://opensource.zalando.com/restful-api-guidelines/#153)), and fastgtp has none.
- When the engine fails or answers something fastgtp cannot read, answer `502`. The engine is the upstream server here, which is what `502` means in RFC 9110. Spectral warns about it because it is not on Zalando's list of well-understood codes ([#150](https://opensource.zalando.com/restful-api-guidelines/#150)).
- [#180](https://opensource.zalando.com/restful-api-guidelines/#180): Use `Location`, not `Content-Location`.

### Errors

- [#176](https://opensource.zalando.com/restful-api-guidelines/#176): Every 4xx and 5xx error is RFC 9457 problem JSON (`application/problem+json`). Request validation errors too, with status `400`.
- Each problem type has a section in `docs/problems.md`, and its `type` URI points to that section.
- [#177](https://opensource.zalando.com/restful-api-guidelines/#177): No stack traces, file paths or engine stderr in errors. Log them instead.

### Long-running work

- [#253](https://opensource.zalando.com/restful-api-guidelines/#253): Use a job resource. `POST /analysis-jobs` answers `201` with `Location`. `GET /analysis-jobs/{id}` returns the status and, when done, the result.

### Lists

- [#159](https://opensource.zalando.com/restful-api-guidelines/#159), [#160](https://opensource.zalando.com/restful-api-guidelines/#160), [#254](https://opensource.zalando.com/restful-api-guidelines/#254): A list that can grow uses cursor pagination and no total count. A short, fixed list, such as profiles, does not need pagination.

## Rules we skip

| Rule | Why |
| --- | --- |
| #104, #105, #225 (authentication and scopes) | fastgtp has no users. The deployment adds authentication in front of it. |
| #114 (media type versioning) | Only needed for a breaking change, and we avoid those. Revisit if one is needed. |
| #183, #184, #233 (Zalando headers, `X-Flow-ID`) | Zalando-internal. |
| #215, #219, #223, #224 (API id, audience, host names) | Zalando-internal. |
| #218, contact email only | The repository is public. `info.contact.url` points to the repository instead. |
| #185, #186, #188, #190, #191 (deprecation process) | Assume a company with known clients. |
| #193 (monitoring), #156 (gzip), #157, #158 (partial responses, embedding) | Not needed at this size. |
| #163 to #166, #217 (hypermedia links, absolute URIs) | Not needed. `Location` may be relative, as RFC 9110 allows. |
| #112 (open-ended enums) | Our enums are closed. A new value is a new spec version. |
| #229, #231, #230 (idempotent `POST`, `Idempotency-Key`) | Not used for now. Clients resubmit a job when unsure. |

## GTP in resource form

GTP commands are verbs. Turn each one into a resource change instead of putting the verb in the URL (#138):

| GTP | HTTP |
| --- | --- |
| start an engine | `POST /sessions` |
| `quit` | `DELETE /sessions/{session_id}` |
| `play B D4` | `POST /sessions/{session_id}/moves` with `{"color": "BLACK", "vertex": "D4"}` |
| `genmove B` | `POST /sessions/{session_id}/moves` with `{"color": "BLACK"}` (no vertex) |
| `undo` | `DELETE /sessions/{session_id}/moves/last` |
| `clear_board`, `boardsize`, `komi` | `PUT /sessions/{session_id}/board` |
| `showboard`, read the position | `GET /sessions/{session_id}/board` |

There is no route that forwards a raw GTP command.
