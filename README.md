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

## Still Cooking – Contributions Welcome!

fastgtp is under active development. Have ideas, issues, or wishlists?  
[Open an issue](https://github.com/your-org/fastgtp/issues) and let’s build the ultimate GTP gateway together.

If this project sparks joy, **drop us a ⭐️**. It helps more Go developers discover fastgtp!

## LICENSE

This project is licensed under the PolyForm Noncommercial License 1.0.0.  
You may use it freely for personal or noncommercial purposes.  
Commercial use is prohibited.  
