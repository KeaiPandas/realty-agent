"""线索情报 API"""
from fastapi import APIRouter

from services.leads.risk_engine import get_risk_leads, update_all_risks
from services.leads.action_extractor import get_today_actions, extract_actions_from_leads
from services.leads.briefing import generate_briefing
from services.leads.stats import get_stats
from services.db import update_action

router = APIRouter()


@router.get("/risk")
def leads_risk():
    leads = get_risk_leads()
    summary = {"high": 0, "medium": 0, "low": 0}
    for l in leads:
        summary[l["risk_level"]] = summary.get(l["risk_level"], 0) + 1
    # 自动提取待办
    extract_actions_from_leads(leads)
    return {"leads": leads, "summary": summary}


@router.get("/actions")
def leads_actions():
    return {"actions": get_today_actions()}


@router.post("/actions/{action_id}/done")
def action_done(action_id: int):
    ok = update_action(action_id, "done")
    return {"ok": ok}


@router.post("/actions/{action_id}/skip")
def action_skip(action_id: int):
    ok = update_action(action_id, "skipped")
    return {"ok": ok}


@router.get("/briefing")
def leads_briefing():
    return generate_briefing()


@router.get("/stats")
def leads_stats():
    return get_stats()


@router.post("/refresh")
def refresh_risks():
    summary = update_all_risks()
    leads = get_risk_leads()
    extract_actions_from_leads(leads)
    return {"ok": True, "summary": summary}
