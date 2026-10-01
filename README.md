# AirBreda

Does traffic on the A27 near Breda push up NO2? Two live data streams (Luchtmeetnet station NL10240 and four NDW sites hrl, hrr, vwd, vwa) are ingested into Azure, a linear regression predicts NO2 from traffic, and a dashboard serves it.

## Live system
Dashboard: http://9.160.167.34:8000 | Endpoints: `/`, `/site/{hrl|hrr|vwd|vwa}`, `/history`, `/health`

## Layout
- `ingest_air.py`, `ingest_traffic.py`, `quality.py`: ingestion and data-quality handlers (Luchtmeetnet stale/null flagged and kept; NDW speed=-1 excluded and logged)
- `getTrafficReadings.py`: NDW XML parsing helpers (course-provided)
- `build_training_data.py`, `train.py`, `predict.py`, `model.pkl`, `model_info.json`: model pipeline
- `dashboard.py`, `index.html`: FastAPI app and page
- `Dockerfile`, `Dockerfile.traffic`, `Dockerfile.dashboard`, `docker-compose.yml`, `deploy.sh`
- `tests/`: pytest tests
- `docs/architecture-design-document.md`: architecture and ADR-001 to ADR-006

## Run
Create a `.env` with `DATABASE_URL` and a storage connection string or `STORAGE_ACCOUNT` (never commit it). Then `docker compose up --build`, or `python train.py && ./deploy.sh` to retrain and redeploy.
