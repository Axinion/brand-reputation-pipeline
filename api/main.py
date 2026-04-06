import warnings
warnings.filterwarnings("ignore")

import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from contextlib import asynccontextmanager

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
import sqlite_utils

from config import BRAND_NAME, DB_PATH


# ── startup ────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Brand Reputation API starting up", flush=True)
    print(f"  Brand  : {BRAND_NAME}", flush=True)
    print(f"  DB     : {DB_PATH}", flush=True)
    print("  Docs   : http://localhost:8000/docs", flush=True)
    yield
    print("Brand Reputation API shutting down", flush=True)


app = FastAPI(
    title       = f"{BRAND_NAME} Brand Reputation API",
    description = (
        "REST API for the Multi-Source Brand Reputation Intelligence Pipeline. "
        "Serves health scores, alerts, and generated reports."
    ),
    version  = "1.0.0",
    lifespan = lifespan,
)


# ── helpers ────────────────────────────────────────────────────────────

def _db_path() -> Path:
    p = Path(DB_PATH)
    return p if p.is_absolute() else ROOT / p


def get_db():
    """Open DB connection — returns None if DB doesn't exist yet."""
    path = _db_path()
    if not path.exists():
        return None
    return sqlite_utils.Database(str(path))


def latest_report_path():
    """Find the most recently generated HTML report."""
    outputs = ROOT / "outputs"
    if not outputs.exists():
        return None
    reports = sorted(outputs.glob("*.html"), key=lambda p: p.stat().st_mtime)
    return reports[-1] if reports else None


# ── pipeline runner (background task) ─────────────────────────────────

_pipeline_status = {
    "running":    False,
    "last_run":   None,
    "last_result": None,
}


def _run_pipeline_subprocess():
    """
    Run pipeline — disabled on Render (RENDER=true): no NLP / Prefect stack.
    Works locally with full requirements.txt.
    """
    global _pipeline_status
    _pipeline_status["running"]   = True
    _pipeline_status["last_run"]  = datetime.now(tz=timezone.utc).isoformat()

    try:
        if os.getenv("RENDER", "").lower() == "true":
            _pipeline_status["last_result"] = {
                "exit_code": -1,
                "stdout":    "",
                "stderr":    (
                    "Pipeline runs are disabled on Render (demo server). "
                    "Clone the repo and run locally with full requirements.txt."
                ),
                "success":   False,
            }
            return

        result = subprocess.run(
            [sys.executable, str(ROOT / "pipeline" / "prefect_flow.py"), "run"],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=7200,
        )
        _pipeline_status["last_result"] = {
            "exit_code": result.returncode,
            "stdout":    result.stdout[-2000:],
            "stderr":    result.stderr[-500:] if result.returncode != 0 else "",
            "success":   result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        _pipeline_status["last_result"] = {
            "exit_code": -1,
            "stdout":    "",
            "stderr":    "Pipeline timed out after 2 hours",
            "success":   False,
        }
    except FileNotFoundError:
        _pipeline_status["last_result"] = {
            "exit_code": -1,
            "stdout":    "",
            "stderr":    (
                "Pipeline dependencies not installed in this environment. "
                "Run locally with full requirements.txt."
            ),
            "success":   False,
        }
    except Exception as e:
        _pipeline_status["last_result"] = {
            "exit_code": -1,
            "stdout":    "",
            "stderr":    str(e),
            "success":   False,
        }
    finally:
        _pipeline_status["running"] = False


# ── routes ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, tags=["UI"])
async def landing_page():
    """Landing page with project overview and links."""
    db    = get_db()
    score = None
    if db and "brand_health_scores" in db.table_names():
        try:
            row = next(db.execute('''
                SELECT date, health_score, smoothed_score
                FROM brand_health_scores
                WHERE brand = ?
                ORDER BY date DESC LIMIT 1
            ''', [BRAND_NAME]))
            score = {"date": row[0], "score": row[1], "smooth": row[2]}
        except StopIteration:
            pass

    score_html = ""
    if score:
        color = (
            "#1D9E75" if score["score"] >= 65
            else "#BA7517" if score["score"] >= 45
            else "#D85A30"
        )
        score_html = f"""
        <div class="score-hero">
          <div class="score-num" style="color:{color}">
            {score['score']:.1f}
          </div>
          <div class="score-sub">/ 100 &nbsp;·&nbsp; as of {score['date']}</div>
        </div>"""
    else:
        score_html = """
        <div class="score-hero">
          <div class="score-num" style="color:#888">—</div>
          <div class="score-sub">Run the pipeline to generate scores</div>
        </div>"""

    return HTMLResponse(content=f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{BRAND_NAME} Brand Reputation Pipeline</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI",
                   Helvetica, Arial, sans-serif;
      background: #F8F7F4; color: #2C2C2A;
      min-height: 100vh; padding: 48px 16px;
    }}
    .page {{ max-width: 720px; margin: 0 auto; }}
    h1 {{ font-size: 24px; font-weight: 600; margin-bottom: 6px; }}
    .subtitle {{ color: #888780; font-size: 14px; margin-bottom: 40px; }}
    .score-hero {{ text-align: center; margin: 32px 0; }}
    .score-num  {{ font-size: 72px; font-weight: 700; line-height: 1; }}
    .score-sub  {{ color: #888780; font-size: 14px; margin-top: 8px; }}
    .card {{
      background: #fff; border: 0.5px solid #D3D1C7;
      border-radius: 12px; padding: 24px 28px; margin-bottom: 16px;
    }}
    .card h2 {{
      font-size: 13px; font-weight: 600; color: #888780;
      text-transform: uppercase; letter-spacing: 0.05em;
      margin-bottom: 16px;
    }}
    .endpoint-grid {{ display: grid; gap: 10px; }}
    .endpoint {{
      display: flex; align-items: center; gap: 12px;
      padding: 10px 14px; background: #F8F7F4;
      border-radius: 8px; text-decoration: none; color: inherit;
      transition: background 0.15s;
    }}
    .endpoint:hover {{ background: #F1EFE8; }}
    .method {{
      font-size: 10px; font-weight: 700; padding: 2px 6px;
      border-radius: 4px; min-width: 36px; text-align: center;
      letter-spacing: 0.04em;
    }}
    .get  {{ background: #E1F5EE; color: #085041; }}
    .post {{ background: #FAEEDA; color: #633806; }}
    .ep-path {{ font-family: monospace; font-size: 13px; }}
    .ep-desc {{ font-size: 12px; color: #888780; margin-left: auto; }}
    .stack-pills {{ display: flex; flex-wrap: wrap; gap: 8px; }}
    .pill {{
      font-size: 11px; padding: 4px 10px; border-radius: 20px;
      background: #F1EFE8; color: #444441; border: 0.5px solid #D3D1C7;
    }}
    .run-btn {{
      display: block; width: 100%; padding: 14px;
      background: #1D9E75; color: white; border: none;
      border-radius: 8px; font-size: 14px; font-weight: 600;
      cursor: pointer; margin-top: 12px; transition: background 0.15s;
    }}
    .run-btn:hover {{ background: #0F6E56; }}
    .run-btn:disabled {{ background: #9FE1CB; cursor: not-allowed; }}
    #run-status {{
      margin-top: 10px; font-size: 13px; color: #888780;
      text-align: center; min-height: 20px;
    }}
  </style>
</head>
<body>
<div class="page">
  <h1>{BRAND_NAME} Brand Reputation Pipeline</h1>
  <div class="subtitle">
    Multi-source brand monitoring · NLP sentiment · Automated alerts
  </div>

  {score_html}

  <div class="card">
    <h2>API endpoints</h2>
    <div class="endpoint-grid">
      <a href="/report" class="endpoint">
        <span class="method get">GET</span>
        <span class="ep-path">/report</span>
        <span class="ep-desc">Latest HTML report</span>
      </a>
      <a href="/health-score" class="endpoint">
        <span class="method get">GET</span>
        <span class="ep-path">/health-score</span>
        <span class="ep-desc">Current score (JSON)</span>
      </a>
      <a href="/alerts" class="endpoint">
        <span class="method get">GET</span>
        <span class="ep-path">/alerts</span>
        <span class="ep-desc">Recent alerts (JSON)</span>
      </a>
      <a href="/status" class="endpoint">
        <span class="method get">GET</span>
        <span class="ep-path">/status</span>
        <span class="ep-desc">Pipeline status + DB stats</span>
      </a>
      <a href="/docs" class="endpoint">
        <span class="method get">GET</span>
        <span class="ep-path">/docs</span>
        <span class="ep-desc">Interactive API docs</span>
      </a>
    </div>
  </div>

  <div class="card">
    <h2>Tech stack</h2>
    <div class="stack-pills">
      <span class="pill">Python 3.13</span>
      <span class="pill">PyABSA</span>
      <span class="pill">distilBERT</span>
      <span class="pill">Groq LLM</span>
      <span class="pill">Prefect</span>
      <span class="pill">FastAPI</span>
      <span class="pill">SQLite</span>
      <span class="pill">Slack</span>
      <span class="pill">Matplotlib</span>
      <span class="pill">Jinja2</span>
    </div>
  </div>

  <div class="card">
    <h2>Run pipeline</h2>
    <p style="font-size:13px;color:#888780;margin-bottom:4px">
      Pipeline runs automatically every Sunday via GitHub Actions.
      Data and report update weekly. Trigger a manual run from the
      <a href="https://github.com/Axinion/brand-reputation-pipeline/actions"
         style="color:#1D9E75">Actions tab</a> on GitHub.
    </p>
    <a href="https://github.com/Axinion/brand-reputation-pipeline/actions"
       target="_blank"
       style="display:block;width:100%;padding:14px;background:#534AB7;
              color:white;border:none;border-radius:8px;font-size:14px;
              font-weight:600;cursor:pointer;margin-top:12px;text-align:center;
              text-decoration:none;">
      View pipeline runs on GitHub ↗
    </a>
    <div id="run-status"></div>
  </div>

</div>
<script>
async function triggerRun() {{
  const btn = document.getElementById('run-btn');
  const status = document.getElementById('run-status');
  btn.disabled = true;
  btn.textContent = 'Starting...';
  status.textContent = '';
  try {{
    const r = await fetch('/run', {{method: 'POST'}});
    const data = await r.json();
    if (data.status === 'started') {{
      btn.textContent = 'Pipeline running...';
      status.textContent = 'Started at ' + new Date().toLocaleTimeString()
        + '. Check /status for progress.';
    }} else if (data.status === 'already_running') {{
      btn.textContent = 'Run pipeline now';
      btn.disabled = false;
      status.textContent = 'Pipeline is already running.';
    }} else if (data.status === 'disabled') {{
      btn.textContent = 'Run pipeline now';
      btn.disabled = false;
      status.textContent = data.message || 'Pipeline not available on this server.';
    }}
  }} catch(e) {{
    btn.textContent = 'Run pipeline now';
    btn.disabled = false;
    status.textContent = 'Error: ' + e.message;
  }}
}}
</script>
</body>
</html>""")


@app.get(
    "/health-score",
    tags=["Data"],
    summary="Current brand health score",
)
async def get_health_score():
    """
    Returns the most recent brand health score and 7-day history.
    """
    db = get_db()
    if not db or "brand_health_scores" not in db.table_names():
        raise HTTPException(
            status_code=404,
            detail="No health scores found. Run the pipeline first."
        )

    # latest score
    try:
        latest = next(db.execute('''
            SELECT date, health_score, smoothed_score,
                   raw_score, dominant_aspect
            FROM brand_health_scores
            WHERE brand = ?
            ORDER BY date DESC LIMIT 1
        ''', [BRAND_NAME]))
    except StopIteration:
        raise HTTPException(status_code=404, detail="No scores found")

    # 7-day history
    history = list(db.execute('''
        SELECT date, health_score, smoothed_score
        FROM brand_health_scores
        WHERE brand = ?
        ORDER BY date DESC LIMIT 7
    ''', [BRAND_NAME]).fetchall())

    # aspect breakdown
    aspects = list(db.execute('''
        SELECT aspect,
               ROUND(AVG(avg_score), 3)    AS score,
               ROUND(AVG(positive_pct), 1) AS pos_pct,
               ROUND(AVG(negative_pct), 1) AS neg_pct,
               SUM(mention_count)          AS mentions
        FROM brand_health_daily
        WHERE brand = ?
        AND date >= DATE("now", "-7 days")
        AND aspect != "overall"
        GROUP BY aspect
        ORDER BY score DESC
    ''', [BRAND_NAME]).fetchall())

    return JSONResponse({
        "brand":        BRAND_NAME,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "current": {
            "date":             latest[0],
            "health_score":     round(latest[1], 1),
            "smoothed_score":   round(latest[2], 1),
            "raw_score":        round(latest[3], 4),
            "dominant_aspect":  latest[4],
        },
        "history_7d": [
            {
                "date":           r[0],
                "health_score":   round(r[1], 1),
                "smoothed_score": round(r[2], 1),
            }
            for r in history
        ],
        "aspect_breakdown": [
            {
                "aspect":    r[0],
                "score":     r[1],
                "pos_pct":   r[2],
                "neg_pct":   r[3],
                "mentions":  int(r[4]),
            }
            for r in aspects
        ],
    })


@app.get(
    "/alerts",
    tags=["Data"],
    summary="Recent alerts",
)
async def get_alerts(limit: int = 20):
    """
    Returns recent alerts ordered by z-score magnitude.
    """
    db = get_db()
    if not db or "alerts" not in db.table_names():
        return JSONResponse({"brand": BRAND_NAME, "alerts": []})

    lim = max(1, min(limit, 100))
    rows = list(db.execute('''
        SELECT alert_type, aspect, date, score,
               baseline_mean, z_score, severity, mention_count
        FROM alerts
        WHERE brand = ?
        ORDER BY ABS(z_score) DESC
        LIMIT ?
    ''', [BRAND_NAME, lim]).fetchall())

    return JSONResponse({
        "brand":        BRAND_NAME,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "count":        len(rows),
        "alerts": [
            {
                "alert_type":    r[0],
                "aspect":        r[1],
                "date":          r[2],
                "score":         round(r[3], 4),
                "baseline_mean": round(r[4], 4),
                "z_score":       round(r[5], 2),
                "severity":      r[6],
                "mention_count": int(r[7]),
            }
            for r in rows
        ],
    })


@app.get(
    "/report",
    response_class=HTMLResponse,
    tags=["UI"],
    summary="Latest generated report",
)
async def get_report():
    """
    Serves the most recently generated HTML report.
    """
    path = latest_report_path()
    if not path:
        return HTMLResponse(
            content="""<html><body style='font-family:sans-serif;
            padding:48px;max-width:600px;margin:0 auto'>
            <h2>No report found</h2>
            <p>Run the pipeline first to generate a report.</p>
            <p><a href='/'>← Back to home</a></p>
            </body></html>""",
            status_code=404,
        )
    return HTMLResponse(content=path.read_text(encoding="utf-8"))


@app.post(
    "/run",
    tags=["Pipeline"],
    summary="Trigger a full pipeline run",
)
async def trigger_run(background_tasks: BackgroundTasks):
    """
    Starts a full pipeline run in the background.
    Returns immediately — check /status for progress.
    On Render (RENDER=true), pipeline is not available — returns status disabled.
    """
    if os.getenv("RENDER", "").lower() == "true":
        return JSONResponse({
            "status":  "disabled",
            "message": (
                "Pipeline runs are not available on this hosted demo. "
                "Data and reports are pre-generated; run the repo locally "
                "with full requirements.txt for end-to-end execution."
            ),
            "check": "/status",
        })

    if _pipeline_status["running"]:
        return JSONResponse({
            "status":   "already_running",
            "message":  "Pipeline is already running",
            "started":  _pipeline_status["last_run"],
        })

    background_tasks.add_task(_run_pipeline_subprocess)

    return JSONResponse({
        "status":  "started",
        "message": "Pipeline started in background",
        "started": datetime.now(tz=timezone.utc).isoformat(),
        "check":   "/status",
    })


@app.get(
    "/status",
    tags=["Pipeline"],
    summary="Pipeline status and DB stats",
)
async def get_status():
    """
    Returns current pipeline run status and database record counts.
    """
    db     = get_db()
    tables = {}

    if db:
        for table in [
            "raw_mentions", "scored_mentions",
            "brand_health_daily", "brand_health_scores",
            "alerts", "alert_log",
        ]:
            try:
                tables[table] = db[table].count
            except Exception:
                tables[table] = 0

    report_path = latest_report_path()
    dbp = _db_path()

    return JSONResponse({
        "brand":          BRAND_NAME,
        "generated_at":   datetime.now(tz=timezone.utc).isoformat(),
        "pipeline": {
            "running":     _pipeline_status["running"],
            "last_run":    _pipeline_status["last_run"],
            "last_result": _pipeline_status["last_result"],
        },
        "database": {
            "path":   str(dbp),
            "exists": dbp.exists(),
            "tables": tables,
        },
        "latest_report": {
            "path":     str(report_path) if report_path else None,
            "modified": datetime.fromtimestamp(
                report_path.stat().st_mtime, tz=timezone.utc
            ).isoformat() if report_path else None,
        },
    })


# ── entry point ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
