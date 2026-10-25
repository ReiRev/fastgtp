# fastgtp

Fast-track your Go engine to the web! **fastgtp** wraps any Go Text Protocol (GTP) engine in a blazing-fast FastAPI service so you can ship HTTP-ready endpoints without taming stdin/stdout pipes by hand.

## Why fastgtp?

- ⚫ **Built for Go AI** – GTP is the language of top-tier Go engines, but it speaks only through stdio.  
  fastgtp translates it into REST so your engine can join modern platforms, dashboards, and MLOps stacks.
- 🌐 **HTTP-first** – Turn `genmove`, `play`, `printsgf`, and custom commands into HTTPS endpoints in minutes.  
  No more glue scripts or brittle shell wrappers.
- 🚀 **Developer-friendly** – Powered by FastAPI, Pydantic models, and async I/O, it scales from hackathon prototypes to production bots.

## Quick Start

```python
from fastgtp import create_app, GTPTransportManager, SubprocessGTPTransport

transport = SubprocessGTPTransport("katago gtp -config /path/to/fastgtp.cfg -model /path/to/network.bin.gz")
manager = GTPTransportManager(transport)
app = create_app(manager)

# run with: uvicorn fastgtp.server.main:app --reload
```

Once the app is running:

```bash
curl -X POST http://localhost:8000/open_session
# => {"session_id": "..."}

curl http://localhost:8000/<session_id>/name
# => {"name": "KataGo"}

## Run with Docker Compose

Launch the full stack (fastgtp + KataGo) with one command:

```bash
docker compose up --build
```

By default the service listens on `localhost:8000` and persists KataGo networks/logs in managed volumes.  
Need to tweak ports or engine arguments? Drop overrides in `.env`:

```env
FASTGTP_PORT=9000
FASTGTP_ENGINE="katago gtp -config /opt/katago/configs/fastgtp.cfg -model /opt/katago/networks/kata1-b28c512nbt-s11233360640-d5406293331.bin.gz"
```

The compose file ships with a KataGo command for convenience, but you can point `FASTGTP_ENGINE` to **any** GTP-compatible binary—Leela Zero, ELF, your homebrew bot, you name it.

Mount custom configs or networks via `docker-compose.yml`:

```yaml
    volumes:
      - ./my-fastgtp.cfg:/opt/katago/configs/fastgtp.cfg:ro
      - ./my-network.bin.gz:/opt/katago/networks/my-network.bin.gz:ro
```

Then rerun `docker compose up` and you’re ready to curl.

## Win Rate Analysis (KataGo)

fastgtp can also analyze a whole game and return Black's win rate after each move. It does this with GTP alone: standard commands replay the game, and KataGo's GTP extensions (`kata-set-rules`, `set_position`, `rectangular_boardsize`, `kata-search_analyze`) set the rules and search each position. An engine without these commands can still serve the session routes above.

### Profiles

A profile fixes everything that changes a result: the engine, the network, the config file, and the number of visits. Clients choose a profile by name. To change a setting, add a profile under a new name instead of editing an existing one, so a name always means the same settings.

```toml
# profiles.toml. Relative paths are resolved against this file.
[profiles."winrate-v1"]
command  = "/opt/katago/katago gtp"
model    = "networks/kata1-tf3-b11c768-s11003M-d5973M-7gres.bin.gz"
config   = "winrate-v1.gtp.cfg"
visits   = 200
maxTurns = 600
```

fastgtp starts KataGo with `-override-config maxVisits=<visits>,reportAnalysisWinratesAs=BLACK`.

Every job runs in a fresh engine process, so earlier jobs cannot change its result. With `numSearchThreads = 1` and `nnRandomize = false` in the config file, the same job on the same engine build and GPU returns the same numbers, digit for digit. The process exits when the job ends, so the network does not stay on the GPU.

```bash
FASTGTP_PROFILES=/path/to/profiles.toml uvicorn fastgtp.server.main:app
```

Set `FASTGTP_ENGINE` as well to serve the session routes from the same app. These optional variables tune jobs: `FASTGTP_MAX_RUNNING_JOBS` (2), `FASTGTP_MAX_QUEUED_JOBS` (100), `FASTGTP_JOB_TIMEOUT_SECONDS` (1800), `FASTGTP_JOB_RETENTION_SECONDS` (3600), and `FASTGTP_RETRY_AFTER_SECONDS` (5).

### Jobs

An analysis can take minutes, so it runs as a job. Submit the game, then poll until the job finishes:

```bash
curl -i -X POST http://localhost:8000/v1/analyses \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: game-42' \
  -d '{
    "profile": "winrate-v1",
    "board": {"width": 19, "height": 19},
    "rules": "japanese",
    "komi": 6.5,
    "setup": [],
    "moves": [{"color": "B", "point": "Q16"}, {"color": "W", "point": "D4"}]
  }'
# => 202 Accepted, Location: /v1/analyses/<id>, Retry-After: 5
# => {"id": "<id>", "status": "queued", "progress": {"done": 0, "total": 3}, ...}

curl http://localhost:8000/v1/analyses/<id>
# => {"status": "succeeded", "result": {
#      "profile": "winrate-v1",
#      "conditions": {"engine": {...}, "model": {"name": "...", "sha256": "..."},
#                     "configSha256": "...", "visits": 200},
#      "turns": [{"turn": 0, "blackWinrate": 0.47}, {"turn": 1, "blackWinrate": 0.46}, ...]}}
```

- `turns` in the request picks the positions to analyze. Turn `n` is the position after `n` moves. Without it, every position is analyzed.
- `initialPlayer` sets the side that plays first when there are no moves. It defaults to White when there are setup stones, and to Black otherwise.
- `conditions` records what decided the numbers. Store it with the results.
- A job is `queued`, `running`, `succeeded`, `failed`, or `canceled`. A failed job has an `error` in RFC 9457 problem details form, for example an illegal move with its index in `field`.
- `DELETE /v1/analyses/<id>` cancels a job. `GET /v1/profiles` lists the profiles and their conditions, and `GET /v1/health` reports job counts.
- Jobs live in memory. After a restart, a job returns 404, and the client should submit it again. Finished jobs are dropped after the retention period.
- Errors from `/v1` routes use `application/problem+json`. The session routes keep their existing error format.

## Still Cooking – Contributions Welcome!

fastgtp is under active development. Have ideas, issues, or wishlists?  
[Open an issue](https://github.com/your-org/fastgtp/issues) and let’s build the ultimate GTP gateway together.

If this project sparks joy, **drop us a ⭐️**. It helps more Go developers discover fastgtp!

## LICENSE

This project is licensed under the PolyForm Noncommercial License 1.0.0.  
You may use it freely for personal or noncommercial purposes.  
Commercial use is prohibited.  
