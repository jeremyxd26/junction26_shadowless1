# shadowless1 — Junction 2026

Work in progress.

## Run

The core service is a Python 3.11 FastAPI app. It reads its settings from environment variables, or from `.env` in the repository root (see `.env.example`). Without `DATABASE_URL` it still starts, and `/readyz` returns 503.

From the repository root, in a virtual environment:

```
pip install -r core/requirements.txt
uvicorn core.app.main:create_app --factory --port 8000   # start the core service
pytest core -q                                            # run the tests
```

`curl localhost:8000/healthz` returns `{"status":"ok","demo_today":"2026-09-30"}`. `curl localhost:8000/readyz` returns 200 when the database answers `SELECT 1`, and 503 with a short reason otherwise.

Settings:
- `DATABASE_URL`
- `DEMO_TODAY` (default `2026-09-30`)
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `CORS_ORIGINS`: comma-separated app origins. The default allows the local dev servers on ports 3000 and 5173.

The tests that need a database are skipped when `DATABASE_URL` is not set.

## Data

**The shared team database is already loaded. Do not run the loader against it.** The loader is only for an empty database: a fresh instance or a local one. On a database where `transactions` already has rows, it refuses to run. A re-run with `--force` drops and recreates every table, so the data is gone for everyone for several minutes.

The app runs on the synthetic S-Pankki dataset from the Junction 2026 "Personal Economic Trainer" challenge. The dataset is not stored in this repository.

To load it into an empty database:

1. Download it into `data/s-pankki` (the transactions file is stored with Git LFS):
   ```
   git lfs install
   git clone https://github.com/hackjunction/Junction-2026-S-pankki.git data/s-pankki
   ```
2. Set `DATABASE_URL` (PostgreSQL) in `.env`; see `.env.example`.
3. Load it:
   ```
   pip install -r core/requirements.txt
   python core/ingest/load.py data/s-pankki
   ```
   This creates the tables `transactions`, `customers`, `mortgage_applications` and `mortgage_events`, and prints the number of rows inserted into each.

## License

MIT
