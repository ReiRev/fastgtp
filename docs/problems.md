# Problem types

Errors from the `/v1` routes are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details, sent as `application/problem+json`. A failed job has the same object in its `error` field.

The `type` field names the kind of error. It is this page's URL followed by one of the anchors below. Compare `type`, not `title`, to tell errors apart. An error with `type: "about:blank"` is a plain HTTP error, such as an unknown route or a wrong method, and its `title` is the HTTP status phrase.

## invalid-request

422. The body or the parameters do not match the request schema. `errors` lists each problem with its location (`loc`), message (`msg`) and error code (`type`).

## unknown-profile

422. No profile has the name in `profile`. `field` is `"profile"`. `GET /v1/profiles` lists the profiles.

## too-many-turns

422. The job would analyze more positions than the profile allows. `field` is `"moves"`. The limit is `limits.maxTurns` in `GET /v1/profiles`.

## idempotency-key-reused

422. The `Idempotency-Key` was already used for a request with a different body.

## analysis-not-supported

501. The profile's engine lacks a GTP command that analysis needs. `detail` names the missing commands.

## queue-full

503. Too many jobs are waiting. Try again after the seconds in `Retry-After`.

## unknown-job

404. No job has this id. The job may have been deleted, dropped after the retention period, or lost in a restart. Submit it again.

## illegal-move

422, in a failed job. The engine refused a move. `field` names the move, for example `"moves[10]"`.

## illegal-setup

422, in a failed job. The engine refused the setup stones, for example a stone with no liberties. `field` is `"setup"`.

## engine-error

502, in a failed job. The engine stopped, or answered in a way fastgtp could not use. The server log has the details.

## analysis-timed-out

504, in a failed job. The job ran longer than the server's job timeout.

## internal-error

500, in a failed job. Something unexpected went wrong in fastgtp. The server log has the details.
