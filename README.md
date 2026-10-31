# fastgtp

fastgtp puts a Go engine behind an HTTP API. It runs any engine that speaks the Go Text Protocol (GTP), such as KataGo or GNU Go, and turns GTP commands into REST calls, so a web app does not have to drive the engine's stdin and stdout itself.

It also has an optional KataGo extension, which runs KataGo's analysis engine and lets clients send it analysis queries over HTTP.

## Run it

```bash
poetry install
FASTGTP_ENGINE="gnugo --mode gtp" poetry run uvicorn fastgtp.server.main:app
```

`FASTGTP_ENGINE` is the command that starts the engine. Any GTP engine works, for example `katago gtp -config gtp.cfg -model model.bin.gz`.

Other settings, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `FASTGTP_MAX_SESSIONS` | 8 | The most sessions, and so engine processes, that run at once. |
| `FASTGTP_RETRY_AFTER_SECONDS` | 5 | Sent in `Retry-After` when the session limit is reached. |
| `FASTGTP_KATAGO_CONFIG` | | A settings file that turns on the [KataGo extension](#katago-extension). |

The API is described in [`openapi.yaml`](openapi.yaml). A running server serves it at `/openapi.json` and as interactive documentation at `/docs`. Errors are [RFC 9457](https://www.rfc-editor.org/rfc/rfc9457) problem details, listed in [`docs/problems.md`](docs/problems.md).

## Play a game

Each session is one engine process. Start one:

```bash
curl -X POST http://localhost:8000/sessions
# {"session_id":"e262278eb0314026b29cbb0f0042c454","engine":{"name":"GNU Go","version":"3.8","protocol_version":"2","commands":[...]}}

SESSION=e262278eb0314026b29cbb0f0042c454
```

Set up an empty 9×9 board:

```bash
curl -X PUT http://localhost:8000/sessions/$SESSION/board \
  -H 'content-type: application/json' -d '{"size": 9, "komi": 6.5}'
# {"size":9,"komi":6.5,"sgf":"(;GM[1]FF[4]\nSZ[9]...)"}
```

Play a move, then let the engine answer. A move without `vertex` asks the engine to choose one:

```bash
curl -X POST http://localhost:8000/sessions/$SESSION/moves \
  -H 'content-type: application/json' -d '{"color": "BLACK", "vertex": "E5"}'
# {"color":"BLACK","vertex":"E5"}

curl -X POST http://localhost:8000/sessions/$SESSION/moves \
  -H 'content-type: application/json' -d '{"color": "WHITE"}'
# {"color":"WHITE","vertex":"C4"}
```

Read the board as SGF, take back the last move, and stop the engine:

```bash
curl http://localhost:8000/sessions/$SESSION/board
curl -X DELETE http://localhost:8000/sessions/$SESSION/moves/last
curl -X DELETE http://localhost:8000/sessions/$SESSION
```

`PUT /sessions/{session_id}/board` also takes `{"sgf": "..."}` to load a game record.

## KataGo extension

The extension runs `katago analysis`, KataGo's [analysis engine](https://github.com/lightvector/KataGo/blob/master/docs/Analysis_Engine.md), and keeps its names and formats: a query here is a query of the analysis engine. Its routes are described in [`fastgtp/katago/openapi.yaml`](fastgtp/katago/openapi.yaml), and they are added to `/openapi.json` when the extension is on.

To turn it on, copy [`examples/katago.toml`](examples/katago.toml), set the KataGo command, config and model in it, and point `FASTGTP_KATAGO_CONFIG` at it:

```bash
FASTGTP_ENGINE="gnugo --mode gtp" FASTGTP_KATAGO_CONFIG=katago.toml \
  poetry run uvicorn fastgtp.server.main:app
```

Each `[katago.<name>]` table in the file starts one KataGo, served under `/katago/<name>`. Send a query:

```bash
curl -i -X POST http://localhost:8000/katago/default/queries \
  -H 'content-type: application/json' \
  -d '{"rules": "japanese", "komi": 6.5, "boardXSize": 19, "boardYSize": 19,
       "moves": [["B", "Q16"], ["W", "D4"]], "maxVisits": 100}'
# HTTP/1.1 201 Created
# location: /katago/default/queries/a8544bb5eeda4e6997c1ca11a298262f
# retry-after: 1
```

Then read it at `Location` until its `status` is `SUCCEEDED` or `FAILED`:

```bash
curl http://localhost:8000/katago/default/queries/a8544bb5eeda4e6997c1ca11a298262f
# {"id":"a8544bb5eeda4e6997c1ca11a298262f","status":"SUCCEEDED","query":{...},"responses":[{"turnNumber":2,"rootInfo":{"winrate":0.47,...},"moveInfos":[...],...}],...}
```

Winrates, scores and ownership are from Black's point of view. KataGo checks the game itself, so a query with an illegal move ends as `FAILED` with KataGo's error, such as `{"error": "Illegal move 3: Q16", "field": "moves"}`.

## Docker Compose

The image includes KataGo and a network, and needs an NVIDIA GPU. Compose reads settings from `.env`, so create it first:

```bash
cp .env.sample .env
docker compose up --build
```

The service listens on port 8000 on every interface of the host, and runs KataGo in GTP mode. To change the port or the engine, edit `.env`:

```env
FASTGTP_PORT=9000
FASTGTP_ENGINE="katago gtp -config /opt/katago/configs/fastgtp.cfg -model /opt/katago/networks/kata1-b28c512nbt-s11233360640-d5406293331.bin.gz"
```

KataGo's example configs, including `analysis_example.cfg`, are in `/opt/katago/configs` in the image, for use in a KataGo extension settings file.

## Development

```bash
poetry run pytest -q -k "not katago"
uvx black --check fastgtp tests
```

The tests run against GNU Go and a fake analysis engine. The KataGo variants of the tests need KataGo from the dev container, so `-k "not katago"` leaves them out.

Issues and pull requests are welcome at [github.com/ReiRev/fastgtp](https://github.com/ReiRev/fastgtp/issues).

## License

fastgtp is licensed under the [Apache License 2.0](LICENSE). You may use, change and share it, also for commercial purposes, as the license describes.
