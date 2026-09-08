# Metafile

Sign up → create metafiles → add blocks → manage it all from the dashboard.
A metafile is a portable container holding any number of typed blocks
(memory, spreadsheet, page, canvas, calendar, timer, media) that any AI
(or human) can fetch, query, and mutate through one link — with
capability-URL share links, optimistic-concurrency versioning, per-edit
agent fingerprinting, and semantic search over facts.

**AI agents:** the machine-readable guide is served at `/llms.txt` (and
`/ai`). Hitting the root URL without a browser Accept header returns the
guide directly — the doc is the first thing an agent reads.

## Run it

```bash
cd backend
pip install -r requirements.txt
python run.py            # serves http://localhost:8000 (dual-stack)
```

Or double-click `start-server.bat` in the repo root.

## Deploy (Railway)

The repo is Railway-ready (`railway.json` + root `requirements.txt` +
`Procfile`):

1. Push to GitHub, then in Railway: **New Project → Deploy from GitHub
   repo** and pick this repository.
2. Set these variables in the service (Settings → Variables):
   - `SECRET_KEY` — long random string (generate:
     `python -c "import secrets; print(secrets.token_hex(32))"`).
     Without it, a new key is minted per deploy and login sessions reset.
   - `APP_URL` — your Railway public URL (used for Paystack redirects).
   - `ALLOW_FREE_UPGRADE=false` — the dev bypass must be off in public.
   - `PAYSTACK_SECRET_KEY` / `PAYSTACK_PUBLIC_KEY` — when taking payments.
   - `DATABASE_URL` — e.g. `sqlite:////data/metafile.db` **with a volume
     mounted at `/data`** (Settings → Volumes). Without a volume, data is
     ephemeral and resets on every redeploy.
3. Deploy. Health check runs against `/llms.txt`; the port is taken from
   Railway's `PORT` automatically.

Note: run a single worker — the SSE live-sync bus is in-process
(swap in redis before scaling horizontally).

## Flow

1. **Auth** — create an account or sign in (email + password, PBKDF2-hashed,
   HMAC-signed session tokens). No login needed to *use* a share link.
2. **Create a metafile** — a named container. You get a read-write and a
   read-only share link (tokens shown once; rotate them anytime).
3. **Add blocks** — inside the metafile, add any mix of the seven artifact
   types, as many as fit under the size cap. Rename, reorder via tabs,
   delete individually.
4. **Dashboard** — every metafile as a card: block icons, bytes meter,
   tier, rename / upgrade / delete / claim. Legacy ownerless files appear
   as **Unclaimed** — one click adopts them into your account.
5. **Playgrounds / field** (`/session/{id}/{token}`) — a zoomable, pannable
   infinite canvas of windows pinned to specific blocks (scroll to zoom,
   drag to pan), with owner / collaborator links and the AI-proposal
   approval gate.

## Plans & real Paystack payments

- **Free:** 5 MB per metafile. **Paid:** 100 MB, one-time charge.
- Payments run through **Paystack** (card, bank account, bank transfer):
  upgrade modal → secure Paystack checkout → server-side verification →
  tier flips. A signed webhook (`POST /paystack/webhook`) covers async
  confirmations too.
- Configure in `backend/.env`:

```env
PAYSTACK_SECRET_KEY=sk_live_xxx
PAYSTACK_PUBLIC_KEY=pk_live_xxx
UPGRADE_AMOUNT_KOBO=250000   # 2500 NGN
```

- Without keys, upgrading cleanly reports “payments not connected.”
  `ALLOW_FREE_UPGRADE=true` enables a dev-only instant-upgrade endpoint
  for testing — never turn it on in production.

## What's real vs. stubbed

**Real:** account auth; multi-block containers; capability links + rotation;
per-block optimistic concurrency (409 + current state); per-mutation
provenance with block ids; hand-rolled spreadsheet engine (no `eval`);
TF-IDF fact search; server-side size metering; Paystack init/verify/webhook;
live sync over SSE (`/events/m/{id}`, `/events/session/{id}/{token}`) —
any change by any client streams to every open view, studio and field
alike; `place_all` — drop every block of a metafile into a playground as
gridded windows in one versioned op.

**Deliberately simple:** no password reset email; search is TF-IDF, not
embeddings (`search.py` is the seam); SSE uses an in-process bus, so it
needs a single uvicorn worker (use redis for multi-worker); media stays
base64-inline (~33% overhead, so the 5 MB cap holds ~3.7 MB of real
media); HTML renders in a sandboxed iframe.

## API shape (abridged)

- `POST /auth/register|/login`, `GET /auth/me` (Bearer token)
- `GET|POST /metafiles`, `PATCH|DELETE /metafiles/{id}`, `POST …/claim|rotate`
- `POST|DELETE|PATCH /metafiles/{id}/artifacts…`
- `GET /m/{id}?token=…&op=fetch|get|set|append|delete|search|history&artifact=<id>…`
- `POST /m/{id}/bulk` (same ops, JSON body)
- `POST /metafiles/{id}/upgrade/init|verify`, `POST /paystack/webhook`
