# Carb Tracker

Self-hosted carb and fat diary for a NAS. Phone-friendly web app (installable as a PWA).

**Ways to add food**
- **Nutrition label photo**: Claude reads serving size, total carbs and total fat.
- **Meal photo**: Claude identifies items and estimates portions, carbs and fat. These are estimates, so review before adding.
- **Barcode scan**: Open Food Facts lookup. Live scanning needs a browser with `BarcodeDetector` (Chrome/Android); elsewhere you can type the number.
- **Search**: USDA FoodData Central (generic and branded foods) plus Open Food Facts.
- **Manual entry** and one-tap **recent foods**.

Everything lands in an editable draft first, so nothing is logged until you confirm it.
Daily totals show progress against optional carb/fat goals, with a 30-day history chart.

## Run

```sh
cp .env.example .env     # set ANTHROPIC_API_KEY and APP_PASSWORD
docker compose up -d --build
```

Open `http://<nas>:8000` (user `carbs`, password = `APP_PASSWORD`). Data is a single SQLite file in `./data`.

| Variable | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | Required for the photo features |
| `APP_PASSWORD` / `APP_USER` | HTTP basic auth for the whole app. **Set this**: each photo costs API money |
| `USDA_API_KEY` | Free key from fdc.nal.usda.gov; `DEMO_KEY` is rate limited |
| `CLAUDE_MODEL` | Defaults to `claude-opus-5-5`; set a cheaper model if you want to trade accuracy for cost |
| `TZ` | Your timezone |

### TrueNAS
Use Apps → Discover Apps → **Install via YAML** (TrueNAS 24.10+) with `docker-compose.yml`, after building/pushing the image
or building on the box, and replace `./data` with a dataset path such as `/mnt/tank/apps/carbs`.

### Remote access and HTTPS
Camera barcode scanning needs HTTPS (photo upload does not). Either:
- **Tailscale**: `tailscale serve --bg 8000` gives `https://<nas>.<tailnet>.ts.net`.
- **Cloudflare Tunnel**: point a public hostname at `http://localhost:8000`, ideally behind Cloudflare Access too.

## Develop
```sh
pip install -r requirements-dev.txt
python -m pytest
DATA_DIR=./data uvicorn app.main:app --reload
```
