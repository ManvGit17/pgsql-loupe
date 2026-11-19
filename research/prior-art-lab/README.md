# Prior-art lab

Small FastAPI app (`labapp.py`) and one probe per tool, used for `docs/prior-art.md`.

```bash
docker compose up -d --wait
uv run --no-project --python 3.13 run_all.py
docker compose down -v
```

Each probe pins its dependencies in a PEP 723 header. Outputs are written to `results/`.
