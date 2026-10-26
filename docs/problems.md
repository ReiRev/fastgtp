# Problem types

Every 4xx and 5xx error from fastgtp is an [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem, sent as `application/problem+json`:

```json
{
  "type": "https://github.com/ReiRev/fastgtp/blob/main/docs/problems.md#invalid-request",
  "title": "Invalid request",
  "status": 400,
  "detail": "String should match pattern '^([A-HJ-Z][1-9][0-9]?|PASS)$'",
  "field": "vertex"
}
```

- `type` is this page's URL followed by one of the anchors below. Compare `type`, not `title` or `detail`, to tell errors apart.
- `field`, when present, names the part of the request the problem is about, for example `vertex` or `moves[10]`.
- `type: "about:blank"` is a plain HTTP error that fastgtp does not describe further, such as an unknown path (`404`) or a wrong method (`405`). Its `title` is the HTTP status phrase.
- A failed analysis job carries the same object in its `error` field.

Errors never contain stack traces, file paths or engine stderr. fastgtp logs those instead.

## invalid-request

`400`. The body, a parameter or a value in it is not valid, or the engine rejected a value, such as a board size it does not support. `field` names the first invalid part, and `detail` says what is wrong with it. A point off the board in an analysis job is also an `invalid-request`.

## session-not-found

`404`. There is no session with this id. It was deleted, or fastgtp restarted.

## illegal-move

`409` from `POST /sessions/{session_id}/moves`: the move is not legal in the current position.

In a failed analysis job, the status is `400` and `field` names the move, for example `moves[10]`.

## no-move-to-undo

`409`. `DELETE /sessions/{session_id}/moves/last` found no move to take back.

## too-many-sessions

`503`. fastgtp already runs as many sessions as it allows. Delete a session, or try again after the seconds in `Retry-After`.

## profile-not-found

`404` from `GET /profiles/{profile_name}`, and `400` from `POST /analysis-jobs`: there is no profile with this name. `GET /profiles` lists them.

## too-many-moves

`400`. The game has more moves than the profile's `max_moves`. `field` is `moves`.

## analysis-not-supported

`501`. The profile's engine lacks a GTP command that analysis needs. `detail` names the missing commands.

## queue-full

`503`. Too many analysis jobs are waiting. Try again after the seconds in `Retry-After`.

## job-not-found

`404`. There is no analysis job with this id. It was deleted, removed some time after it finished, or lost when fastgtp restarted. Submit it again.

## illegal-setup

In a failed analysis job, with status `400`. The setup stones cannot be placed, for example two stones on one point. `field` is `setup_stones`.

## analysis-timed-out

In a failed analysis job, with status `500`. The job ran longer than the server allows.

## engine-error

`500`. The engine failed, did not start, stopped, or gave a reply fastgtp could not read. When the engine answered with a GTP error, `detail` is that error's text.

## internal-error

`500`. A bug in fastgtp. The details are in the server log.
