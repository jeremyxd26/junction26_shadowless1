# shadowless1 — Junction 2026

Work in progress.

## Run

_One-command run goes here._

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

### Metric marts

The peer benchmark and the grocery store index read three small precomputed tables. Build them once after every data load, and again whenever `DEMO_TODAY` changes. This is safe on the shared database: it never drops anything, it only creates `metric_customer_month`, `metric_peer_flags` and `metric_grocery_cells` if they are missing, and it rewrites their rows one batch at a time.

```
set -a && . ./.env && set +a      # build.py reads DATABASE_URL and DEMO_TODAY from the environment only
python core/marts/build.py
```

It runs 52 batches of 100 customers, printing one line per batch, and takes about 4 minutes. `--dry-run` lists the batches without touching the database, and `--from CUST01200` resumes after an interruption. Design: `docs/design/metrics.md`, section 8.

## License

MIT
