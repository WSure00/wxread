# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

Automated script that fakes reading time on WeRead (微信读书, weread.qq.com) to maintain challenge/streak progress. It replays the `/web/book/read` endpoint with a forged payload once per ~30s for `READ_NUM` iterations, refreshing its session cookie (`wr_skey`) on expiry. Designed to run unattended via GitHub Actions or a Docker+cron container. Comments and README are in Chinese; match that when editing user-facing strings.

## Running

```bash
# Local one-off run (set env vars or edit config.py first)
python main.py

# Docker
docker rm -f wxread && docker build -t wxread . && \
  docker run -d --name wxread -v $(pwd)/logs:/app/logs --restart always wxread
docker exec -it wxread python /app/main.py   # manual test inside container

# GitHub Actions: manual trigger from Actions tab, or scheduled (deploy.yml, BJT 01:00 daily)
```

There are **no tests and no linter configured**. There is no `requirements.txt`; dependencies (`requests`, `urllib3`) are pinned in `Dockerfile` and `deploy.yml` directly.

## Architecture

Four flat modules, no packages, no tests. Entry point is `main.py`, which runs top-level (module-import) code, not a `main()` guard — importing `main` triggers the whole run.

**`config.py`** — single source of configuration. Reads env vars with local defaults as fallback (pattern: `"" or os.getenv(...)` for strings, `int(os.getenv(...) or N)` for ints). Holds:
- `data` — the **request payload template** for the read endpoint (see "字段解释" in README for field meanings). Critical fields like `b`/`c` (book/chapter ids) and `appId` live here; the README explicitly warns to keep `data` as-is (default reads 三体) since other books may not credit time.
- `headers`, `cookies` — redacted templates replaced at runtime.
- `book` / `chapter` — lists sampled randomly per request (`random.choice`) to vary book/chapter per read.
- `convert(curl_str)` — parses a copied `curl -H ... -b ...` bash string into `(headers, cookies)`. At import time, if `WXREAD_CURL_BASH` env var is set, it overrides the local `headers`/`cookies` via this function. This is how GitHub Actions injects credentials.

**`main.py`** — the run loop. `refresh_cookie()` is called once at import/start, then a `while index <= READ_NUM` loop that per iteration:
1. Pops the old `s` (signature) field, randomizes `b`/`c`/`ct`/`rt`/`ts`/`rn`.
2. Computes `sg` = `sha256(f"{ts}{rn}{KEY}")` where `KEY` is a hardcoded salt (reverse-engineered from WeRead's JS).
3. Computes `s` = `cal_hash(encode_data(data))` — a 32-bit DJB2-style hash (`0x15051505` seed) over the URL-encoded sorted key=value payload. Both `sg` and `s` are request-integrity signatures that must match the site's JS algorithm exactly.
4. POSTs to `READ_URL`. Response handling: `succ` present + `synckey` present → success, sleep 30s, increment; `succ` present but no `synckey` → call `fix_no_synckey()` (hits `chapterInfos` to resync); no `succ` → cookie expired, call `refresh_cookie()`.
5. `get_wr_skey()` renews the cookie by POSTing to `RENEW_URL` trying each entry in `COOKIE_DATA_VARIANTS`; returns first 8 chars of the new `wr_skey`.

**`push.py`** — `PushNotification` class wrapping 4 channels (pushplus, telegram, wxpusher, serverchan). The free function `push(content, method, is_success=True)` dispatches by lowercased `method`. pushplus/wxpusher/serverchan have 5-attempt retry loops with random 180–360s backoff; telegram retries once without proxy if the proxied attempt fails. Channel tokens come from `config.py` (env-backed). Push titles carry 成功/失败 status.

**`log_utils.py`** — `setup_logging()` returns a `refresh_print` callback for in-place progress-line updates (carriage-return overwrites). Its custom `RefreshSafeHandler` clears any active progress line before emitting a real log line, routing `WARNING+` to stderr and the rest to stdout. Note it clears `root_logger.handlers` — be aware if adding other log handlers.

## Configuration / Secrets

| Var | Where | Purpose |
|-----|-------|---------|
| `WXREAD_CURL_BASH` | secret | Full `curl` bash of the read endpoint; parsed by `convert()` for headers+cookies. **Required.** |
| `READ_NUM` | repo variable | Read iterations (each ≈30s). Default 40 (≈20 min). |
| `PUSH_METHOD` | secret | `pushplus`/`wxpusher`/`telegram`/`serverchan`; empty = no push. |
| `PUSHPLUS_TOKEN` / `WXPUSHER_SPT` / `TELEGRAM_BOT_TOKEN`+`TELEGRAM_CHAT_ID` / `SERVERCHAN_SPT` | secret | Token for the chosen `PUSH_METHOD`. |
| `http_proxy`/`https_proxy` | env | Optional, for Telegram only. |

Local/Docker deployments edit `config.py` directly (headers, cookies, `READ_NUM`, `PUSH_METHOD`, token). GitHub Actions uses env vars exclusively.

## Key Constraints When Editing

- **Do not change `data` structure or `KEY`/`cal_hash`/`encode_data` algorithms** — these mirror WeRead's client-side signing; altering them breaks request validation (responses lose `succ`/`synckey`).
- **Per-read timing is 30s** (`time.sleep(30)`); `READ_NUM * 0.5` minutes is the credited duration shown in logs/pushes.
- The run loop runs at **module import time** with no `if __name__ == "__main__":` guard — don't import `main` from elsewhere expecting a no-op.
- GitHub Actions uses a named environment `AutoRead` and has a keepalive job to prevent scheduled-workflow disablement.
