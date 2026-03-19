"""MCP server for grant_hunter - stdio transport."""

from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

from grant_hunter.config import DATA_HOME, SNAPSHOTS_DIR, REPORTS_DIR

# ── Config helpers ─────────────────────────────────────────────────────────────

CONFIG_FILE = DATA_HOME / "config.json"


def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {"email": "", "data_dir": str(DATA_HOME)}


def _save_config(config: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


# ── Async job management ───────────────────────────────────────────────────────

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()

_JOB_TTL_SECONDS = 3600  # keep completed jobs for 1 hour


def _prune_old_jobs() -> None:
    """Remove completed/failed jobs older than _JOB_TTL_SECONDS. Call with _jobs_lock held."""
    cutoff = datetime.utcnow() - timedelta(seconds=_JOB_TTL_SECONDS)
    to_delete = [
        jid
        for jid, job in _jobs.items()
        if job["status"] in ("completed", "failed")
        and job.get("completed_at") is not None
        and job["completed_at"] < cutoff
    ]
    for jid in to_delete:
        del _jobs[jid]

_SOURCE_MAP = {
    "nih": "grant_hunter.collectors.nih.NIHCollector",
    "eu": "grant_hunter.collectors.eu_portal.EUPortalCollector",
    "grants_gov": "grant_hunter.collectors.grants_gov.GrantsGovCollector",
}

ALL_SOURCES = list(_SOURCE_MAP.keys())


def _get_collector(source_name: str):
    """Instantiate a collector by source name."""
    import importlib
    dotted = _SOURCE_MAP[source_name]
    module_path, cls_name = dotted.rsplit(".", 1)
    module = importlib.import_module(module_path)
    return getattr(module, cls_name)()


def _run_collection_job(job_id: str, sources: list[str] | None, test: bool) -> None:
    """Background thread: run collectors one by one."""
    from grant_hunter.filters import filter_grants
    from grant_hunter.eligibility import EligibilityEngine
    from grant_hunter.scoring import RelevanceScorer
    from grant_hunter.report_generator import generate_html_report
    from grant_hunter.dashboard import generate_dashboard

    target_sources = sources or ALL_SOURCES
    with _jobs_lock:
        _prune_old_jobs()
        _jobs[job_id]["pending_sources"] = list(target_sources)

    all_grants = []
    source_stats: dict[str, dict] = {}

    try:
        for src_name in target_sources:
            try:
                collector = _get_collector(src_name)
                if test:
                    # Monkey-patch max pages for test mode
                    for attr in ("max_pages", "MAX_PAGES", "_max_pages"):
                        if hasattr(collector, attr):
                            setattr(collector, attr, 1)
                grants = collector.collect()
                if grants:
                    collector.save_snapshot(grants)
                all_grants.extend(grants)
                source_stats[src_name] = {"collected": len(grants), "filtered": 0}
            except Exception as exc:
                source_stats[src_name] = {"collected": 0, "filtered": 0, "error": str(exc)}
            finally:
                with _jobs_lock:
                    _jobs[job_id]["completed_sources"].append(src_name)
                    _jobs[job_id]["pending_sources"] = [
                        s for s in _jobs[job_id]["pending_sources"] if s != src_name
                    ]

        filtered = filter_grants(all_grants)
        for src_name in source_stats:
            src_filtered = [g for g in filtered if g.source == src_name]
            source_stats[src_name]["filtered"] = len(src_filtered)

        elig_engine = EligibilityEngine()
        scorer = RelevanceScorer()
        eligibility_map: dict = {}
        eligibility_reason_map: dict = {}
        score_map: dict = {}
        eligible = uncertain = ineligible = 0
        for g in filtered:
            fp = g.fingerprint()
            r = elig_engine.check(g)
            g.relevance_score = scorer.score(g)
            eligibility_map[fp] = r.status
            eligibility_reason_map[fp] = r.reason
            score_map[fp] = g.relevance_score
            if r.status == "eligible":
                eligible += 1
            elif r.status == "uncertain":
                uncertain += 1
            else:
                ineligible += 1

        run_date = datetime.utcnow()
        report_path = generate_html_report(
            new_grants=filtered,
            changed_grants=[],
            all_filtered=filtered,
            stats={s: {"success": True, **v} for s, v in source_stats.items()},
            run_date=run_date,
            eligibility_map=eligibility_map,
            eligibility_reason_map=eligibility_reason_map,
        )
        dashboard_path = generate_dashboard(
            all_filtered=filtered,
            eligibility_map=eligibility_map,
            eligibility_reason_map=eligibility_reason_map,
            score_map=score_map,
            stats={s: {"success": True, **v} for s, v in source_stats.items()},
            run_date=run_date,
        )

        with _jobs_lock:
            _jobs[job_id]["result"] = {
                "total_collected": sum(s["collected"] for s in source_stats.values()),
                "filtered": len(filtered),
                "eligible": eligible,
                "uncertain": uncertain,
                "ineligible": ineligible,
                "sources": source_stats,
                "report_path": str(report_path),
                "dashboard_path": str(dashboard_path),
            }
            _jobs[job_id]["status"] = "completed"
            _jobs[job_id]["completed_at"] = datetime.utcnow()
    except Exception as exc:
        with _jobs_lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["error"] = str(exc)
            _jobs[job_id]["completed_at"] = datetime.utcnow()


# ── Snapshot loader ────────────────────────────────────────────────────────────

def _load_latest_snapshots():
    """Load grants from most recent snapshot files. Returns [] if none exist."""
    from grant_hunter.models import Grant

    grants = []
    if not SNAPSHOTS_DIR.exists():
        return grants
    for f in SNAPSHOTS_DIR.glob("*_*.json"):
        try:
            with open(f) as fh:
                data = json.load(fh)
            for item in data:
                try:
                    grants.append(Grant.from_dict(item))
                except Exception:
                    pass
        except Exception:
            pass
    return grants


# ── MCP Server ─────────────────────────────────────────────────────────────────

server = Server("grant-hunter")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="grant_collect",
            description="Start a background grant collection job from configured sources.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of source names to collect from. Defaults to all sources.",
                    },
                    "test": {
                        "type": "boolean",
                        "description": "If true, collect only 1 page per source (fast test mode).",
                        "default": False,
                    },
                },
            },
        ),
        types.Tool(
            name="grant_collect_status",
            description="Poll the status of a collection job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by grant_collect."},
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="grant_collect_result",
            description="Get the results of a completed collection job.",
            inputSchema={
                "type": "object",
                "properties": {
                    "job_id": {"type": "string", "description": "Job ID returned by grant_collect."},
                },
                "required": ["job_id"],
            },
        ),
        types.Tool(
            name="grant_search",
            description="Search stored grants by keyword query.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query text."},
                    "source": {"type": "string", "description": "Filter by source name."},
                    "min_score": {"type": "number", "description": "Minimum relevance score (0-1)."},
                    "eligible_only": {
                        "type": "boolean",
                        "description": "If true, return only IPK-eligible grants.",
                    },
                    "profile": {
                        "type": "string",
                        "description": "Researcher profile name for scoring (default: 'default'). Use grant_list_profiles to see available profiles.",
                        "default": "default",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="grant_list_profiles",
            description="List available researcher profiles for grant scoring.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        types.Tool(
            name="grant_deadlines",
            description="List upcoming grant deadlines.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "Return deadlines within this many days (default 90).",
                        "default": 90,
                    },
                },
            },
        ),
        types.Tool(
            name="grant_check_eligibility",
            description="Check IPK eligibility for a specific grant.",
            inputSchema={
                "type": "object",
                "properties": {
                    "grant_id": {"type": "string", "description": "Grant ID."},
                    "title": {"type": "string", "description": "Grant title (used if grant_id not provided)."},
                },
            },
        ),
        types.Tool(
            name="grant_report",
            description="Generate an HTML report or interactive dashboard.",
            inputSchema={
                "type": "object",
                "properties": {
                    "format": {
                        "type": "string",
                        "enum": ["html", "dashboard"],
                        "description": "Report format (default: dashboard).",
                        "default": "dashboard",
                    },
                },
            },
        ),
        types.Tool(
            name="grant_config_set",
            description="Set a configuration value (email, data_dir).",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Config key: 'email' or 'data_dir'."},
                    "value": {"type": "string", "description": "Config value."},
                },
                "required": ["key", "value"],
            },
        ),
        types.Tool(
            name="grant_config_get",
            description="Get current configuration values.",
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "Config key to retrieve. Omit to return all config.",
                    },
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    result = await _dispatch(name, arguments)
    return [types.TextContent(type="text", text=json.dumps(result, indent=2, default=str))]


async def _dispatch(name: str, args: dict[str, Any]) -> Any:
    if name == "grant_collect":
        return _tool_grant_collect(args)
    elif name == "grant_collect_status":
        return _tool_grant_collect_status(args)
    elif name == "grant_collect_result":
        return _tool_grant_collect_result(args)
    elif name == "grant_search":
        return _tool_grant_search(args)
    elif name == "grant_deadlines":
        return _tool_grant_deadlines(args)
    elif name == "grant_check_eligibility":
        return _tool_grant_check_eligibility(args)
    elif name == "grant_report":
        return _tool_grant_report(args)
    elif name == "grant_config_set":
        return _tool_grant_config_set(args)
    elif name == "grant_config_get":
        return _tool_grant_config_get(args)
    elif name == "grant_list_profiles":
        return _tool_grant_list_profiles(args)
    else:
        return {"error": f"Unknown tool: {name}"}


# ── Tool implementations ───────────────────────────────────────────────────────

def _tool_grant_collect(args: dict) -> dict:
    sources = args.get("sources") or None
    test = bool(args.get("test", False))
    job_id = str(uuid.uuid4())[:8]
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "completed_sources": [],
            "pending_sources": list(sources or ALL_SOURCES),
            "result": None,
            "error": None,
        }
    t = threading.Thread(
        target=_run_collection_job,
        args=(job_id, sources, test),
        daemon=True,
    )
    t.start()
    return {
        "job_id": job_id,
        "status": "started",
        "sources": sources or ALL_SOURCES,
    }


def _tool_grant_collect_status(args: dict) -> dict:
    job_id = args.get("job_id", "")
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return {"error": f"Job not found: {job_id}"}
        return {
            "status": job["status"],
            "completed_sources": list(job["completed_sources"]),
            "pending_sources": list(job["pending_sources"]),
            "error": job.get("error"),
        }


def _tool_grant_collect_result(args: dict) -> dict:
    job_id = args.get("job_id", "")
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return {"error": f"Job not found: {job_id}"}
        if job["status"] == "running":
            return {"error": "Job still running. Check status with grant_collect_status."}
        if job["status"] == "failed":
            return {"error": job.get("error", "Job failed")}
        return dict(job.get("result") or {"error": "No result available"})


def _tool_grant_search(args: dict) -> list:
    query = args.get("query", "").lower()
    source_filter = args.get("source")
    min_score = args.get("min_score")
    eligible_only = args.get("eligible_only", False)
    profile_name = args.get("profile", "default")

    grants = _load_latest_snapshots()
    if not grants:
        return []

    results = []
    for g in grants:
        # Filter by source
        if source_filter and g.source != source_filter:
            continue
        # Filter by score
        if min_score is not None and g.relevance_score < min_score:
            continue
        # Text match
        searchable = f"{g.title} {g.description} {g.agency}".lower()
        if query and query not in searchable:
            continue
        results.append(g)

    # Eligibility filter
    if eligible_only:
        from grant_hunter.eligibility import EligibilityEngine
        engine = EligibilityEngine()
        results = [g for g in results if engine.check(g).status == "eligible"]

    # Score and sort using specified profile
    from grant_hunter.scoring import RelevanceScorer
    from grant_hunter.profiles import get_profile, list_profiles
    try:
        profile = get_profile(profile_name)
    except KeyError:
        available = ", ".join(list_profiles().keys())
        return {"error": f"Unknown profile '{profile_name}'. Available: {available}"}
    scorer = RelevanceScorer(profile=profile)
    scored = sorted(results, key=lambda g: scorer.score(g), reverse=True)[:20]

    return [
        {
            "id": g.id,
            "title": g.title,
            "agency": g.agency,
            "source": g.source,
            "deadline": g.deadline.isoformat() if g.deadline else None,
            "score": round(scorer.score(g), 3),
            "url": g.url,
            "profile": profile_name,
        }
        for g in scored
    ]


def _tool_grant_list_profiles(args: dict) -> dict:
    from grant_hunter.profiles import list_profiles
    profiles = list_profiles()
    return {"profiles": profiles}


def _tool_grant_deadlines(args: dict) -> list:
    days = int(args.get("days", 90))
    cutoff = date.today() + timedelta(days=days)

    grants = _load_latest_snapshots()
    if not grants:
        return []

    from grant_hunter.scoring import RelevanceScorer
    from grant_hunter.eligibility import EligibilityEngine
    scorer = RelevanceScorer()
    elig_engine = EligibilityEngine()

    upcoming = []
    for g in grants:
        if g.deadline is None:
            continue
        if g.deadline > cutoff:
            continue
        if g.deadline < date.today():
            continue
        days_until = (g.deadline - date.today()).days
        score = scorer.score(g)
        # Tier based on score
        if score >= 0.7:
            tier = "high"
        elif score >= 0.4:
            tier = "medium"
        else:
            tier = "low"
        elig_result = elig_engine.check(g)
        upcoming.append({
            "title": g.title,
            "agency": g.agency,
            "deadline": g.deadline.isoformat(),
            "days_until": days_until,
            "tier": tier,
            "eligibility": elig_result.status,
            "eligibility_reason": elig_result.reason,
            "url": g.url,
        })

    upcoming.sort(key=lambda x: x["days_until"])
    return upcoming


def _tool_grant_check_eligibility(args: dict) -> dict:
    grant_id = args.get("grant_id")
    title = args.get("title")

    if not grant_id and not title:
        return {"error": "Provide grant_id or title"}

    grants = _load_latest_snapshots()
    target = None
    for g in grants:
        if grant_id and g.id == grant_id:
            target = g
            break
        if title and title.lower() in g.title.lower():
            target = g
            break

    if target is None:
        return {"error": "Grant not found in snapshots"}

    from grant_hunter.eligibility import EligibilityEngine
    engine = EligibilityEngine()
    result = engine.check(target)
    return {
        "status": result.status,
        "confidence": result.confidence,
        "reason": result.reason,
        "rules_matched": result.rules_matched,
    }


def _tool_grant_report(args: dict) -> dict:
    fmt = args.get("format", "dashboard")
    grants = _load_latest_snapshots()

    if fmt == "html":
        from grant_hunter.report_generator import generate_html_report
        from grant_hunter.eligibility import EligibilityEngine as _EE
        _ee = _EE()
        _emap: dict = {}
        _ermap: dict = {}
        for g in grants:
            fp = g.fingerprint()
            r = _ee.check(g)
            _emap[fp] = r.status
            _ermap[fp] = r.reason
        path = generate_html_report(
            new_grants=grants,
            changed_grants=[],
            all_filtered=grants,
            stats={},
            run_date=datetime.utcnow(),
            eligibility_map=_emap,
            eligibility_reason_map=_ermap,
        )
    else:
        from grant_hunter.dashboard import generate_dashboard
        from grant_hunter.eligibility import EligibilityEngine
        from grant_hunter.scoring import RelevanceScorer
        elig_engine = EligibilityEngine()
        scorer = RelevanceScorer()
        eligibility_map: dict = {}
        eligibility_reason_map: dict = {}
        score_map: dict = {}
        for g in grants:
            fp = g.fingerprint()
            r = elig_engine.check(g)
            if g.relevance_score == 0.0:
                g.relevance_score = scorer.score(g)
            eligibility_map[fp] = r.status
            eligibility_reason_map[fp] = r.reason
            score_map[fp] = g.relevance_score
        path = generate_dashboard(
            all_filtered=grants,
            eligibility_map=eligibility_map,
            eligibility_reason_map=eligibility_reason_map,
            score_map=score_map,
            stats={},
            run_date=datetime.utcnow(),
        )

    size_kb = round(path.stat().st_size / 1024, 1) if path.exists() else 0
    return {
        "path": str(path),
        "size_kb": size_kb,
        "grant_count": len(grants),
    }


def _tool_grant_config_set(args: dict) -> dict:
    key = args.get("key", "")
    value = args.get("value", "")
    allowed = {"email", "data_dir"}
    if key not in allowed:
        return {"error": f"Unknown key '{key}'. Allowed: {sorted(allowed)}"}
    config = _load_config()
    config[key] = value
    _save_config(config)
    return {"ok": True, "key": key, "value": value}


def _tool_grant_config_get(args: dict) -> dict:
    key = args.get("key")
    config = _load_config()
    if key:
        return {key: config.get(key)}
    return config


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    """Entry point for grant-hunter-serve command."""
    from grant_hunter.config import init_data_dirs
    init_data_dirs()
    asyncio.run(_run_server())


async def _run_server() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    main()
