"""Model Council conclusion for confirmed flags at L2+.

The request is confidential (personnel data): category "classification", at least three
providers, and never DeepSeek or GLM (jev forbidden_seats). Evidence is summarized with short
quotes only (<= 200 chars) - no message bodies.

Adapter order:
  1. NTXP_COUNCIL_URL set   -> POST the request JSON, expect {council_id, agreement, conclusion}
  2. local fallback         -> ask each available allowed provider (Anthropic, OpenAI, xAI,
                               Gemini via their API keys) and compute agreement; needs >= 3
                               providers or it returns None
  3. otherwise None         -> the flag stays for human review
Cost: estimated per seat and capped at config.COUNCIL_CEILING_TASK ($2/task).
"""

import datetime as dt
import hashlib
import json
import logging
import os
import re
import urllib.request
from collections import Counter

from admin_console import config, jev
from admin_console.analytics import google, util

log = logging.getLogger(__name__)

# seat: (env key, est cost per ask USD)
PROVIDERS = {
    "anthropic": ("ANTHROPIC_API_KEY", 0.01),
    "openai": ("OPENAI_API_KEY", 0.01),
    "xai": ("XAI_API_KEY", 0.01),
    "gemini": ("GEMINI_API_KEY", 0.005),
    "deepseek": ("DEEPSEEK_API_KEY", 0.002),   # never used for personnel (forbidden seat)
    "glm": ("GLM_API_KEY", 0.002),             # never used for personnel (forbidden seat)
}
VERDICTS = ("supported", "not_supported", "insufficient")

# Test hook / override: {seat: callable(prompt) -> {"verdict", "conclusion"} | None}
PROVIDER_CALLS = {}
POST = None  # test hook: callable(url, payload) -> dict


def build_request(flag):
    decision = jev.route("council_conclusion")
    args = decision.get("council_args", {})
    ev = [{"source": e.get("source"), "ref": e.get("ref"), "note": util.short_quote(e.get("note"))}
          for e in flag.get("evidence", [])[:8]]
    question = (
        "NTXP LLC owner-review proposal. Based ONLY on the evidence below, is the proposed "
        f"classification supported? KPI: {flag['kpi']}; proposed level L{flag['level']} "
        f"({flag['severity']}, {flag['urgency']}). Cross-check: "
        f"{flag.get('crosscheck', {}).get('status')} - "
        f"{' | '.join(flag.get('crosscheck', {}).get('explanations', []))}. "
        "Do not judge the person; say whether the evidence supports the operational concern "
        "and what an owner should verify. Reply as JSON: "
        '{"verdict": "supported|not_supported|insufficient", "conclusion": "<= 2 sentences"}')
    return {
        "confidential": True,
        "category": args.get("category", "classification"),
        "min_providers": max(3, args.get("min_providers", 3)),
        "forbidden_seats": list(decision.get("forbidden_seats") or jev.PERSONNEL_FORBIDDEN_SEATS),
        "ceiling_usd": config.COUNCIL_CEILING_TASK,
        "flag_id": flag.get("id"),
        "summary": util.short_quote(flag.get("summary")),
        "evidence": ev,
        "question": question,
    }


def allowed_seats(request):
    forbidden = {s.lower() for s in request["forbidden_seats"]} | set(jev.PERSONNEL_FORBIDDEN_SEATS)
    seats = []
    for seat, (env, _) in PROVIDERS.items():
        if seat in forbidden:
            continue
        if seat in PROVIDER_CALLS or (os.environ.get(env) and not google.demo()):
            seats.append(seat)
    return seats


def _post(url, payload, timeout=60):
    if POST:
        return POST(url, payload)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    token = os.environ.get("NTXP_COUNCIL_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def _parse(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None
    if data.get("verdict") not in VERDICTS:
        return None
    return {"verdict": data["verdict"], "conclusion": util.short_quote(data.get("conclusion", ""))}


def _ask_anthropic(prompt):
    import anthropic  # lazy: optional dependency
    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=os.environ.get("NTXP_COUNCIL_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
        max_tokens=300, messages=[{"role": "user", "content": prompt}])
    if resp.stop_reason == "refusal":
        return None
    return _parse(next((b.text for b in resp.content if b.type == "text"), ""))


def _ask_openai_compatible(url, key, model, prompt):
    body = {"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 300}
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return _parse(data["choices"][0]["message"]["content"])


def _ask_gemini(prompt):
    key = os.environ["GEMINI_API_KEY"]
    model = os.environ.get("NTXP_COUNCIL_GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    req = urllib.request.Request(url, method="POST", headers={"Content-Type": "application/json"},
                                 data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode())
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    return _parse(data["candidates"][0]["content"]["parts"][0]["text"])


def _ask(seat, prompt):
    if seat in PROVIDER_CALLS:
        return PROVIDER_CALLS[seat](prompt)
    if seat in jev.PERSONNEL_FORBIDDEN_SEATS:
        raise PermissionError(f"{seat} is a forbidden seat for personnel data")
    if seat == "anthropic":
        return _ask_anthropic(prompt)
    if seat == "openai":
        return _ask_openai_compatible("https://api.openai.com/v1/chat/completions",
                                      os.environ["OPENAI_API_KEY"],
                                      os.environ.get("NTXP_COUNCIL_OPENAI_MODEL", "gpt-4.1-mini"), prompt)
    if seat == "xai":
        return _ask_openai_compatible("https://api.x.ai/v1/chat/completions",
                                      os.environ["XAI_API_KEY"],
                                      os.environ.get("NTXP_COUNCIL_XAI_MODEL", "grok-3-mini"), prompt)
    if seat == "gemini":
        return _ask_gemini(prompt)
    return None


def _local(request):
    seats = allowed_seats(request)
    if len(seats) < request["min_providers"]:
        return None
    prompt = request["question"] + "\n\nSummary: " + request["summary"] + "\nEvidence:\n" + \
        "\n".join(f"- [{e['source']}] {e['note']}" for e in request["evidence"])
    spent, answers = 0.0, {}
    for seat in seats:
        cost = PROVIDERS[seat][1]
        if spent + cost > request["ceiling_usd"]:
            break
        spent += cost
        try:
            got = _ask(seat, prompt)
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.info("council seat %s failed: %s", seat, exc)
            got = None
        if got:
            answers[seat] = got
    if len(answers) < request["min_providers"]:
        return None
    tally = Counter(a["verdict"] for a in answers.values())
    verdict, votes = tally.most_common(1)[0]
    text = next(a["conclusion"] for a in answers.values() if a["verdict"] == verdict)
    digest = hashlib.sha1(json.dumps(request, sort_keys=True).encode()).hexdigest()[:8]
    return {"council_id": f"LC-{dt.date.today():%Y%m%d}-{digest}",
            "agreement": round(votes / len(answers), 2),
            "conclusion": util.short_quote(f"Proposal ({verdict}, {votes}/{len(answers)} seats): {text}"),
            "_cost": round(spent, 4), "_seats": sorted(answers)}


def conclude(flag):
    """Return {council_id, agreement, conclusion} or None (left for human review)."""
    request = build_request(flag)
    if not request["confidential"] or not {"deepseek", "glm"} <= set(request["forbidden_seats"]):
        raise PermissionError("personnel council requests must be confidential and exclude DeepSeek/GLM")
    url = os.environ.get("NTXP_COUNCIL_URL", "").strip()
    if url and not google.demo():
        try:
            resp = _post(url, request)
            if resp and resp.get("council_id"):
                return {"council_id": str(resp["council_id"]),
                        "agreement": float(resp.get("agreement") or 0.0),
                        "conclusion": util.short_quote(resp.get("conclusion", ""))}
        except Exception as exc:  # noqa: BLE001
            log.info("council URL failed, trying local fallback: %s", exc)
    try:
        result = _local(request)
    except PermissionError:
        return None
    if result is None:
        return None
    return {k: result[k] for k in ("council_id", "agreement", "conclusion")}


def status():
    if os.environ.get("NTXP_COUNCIL_URL"):
        return "ok"
    return "ok" if len(allowed_seats({"forbidden_seats": list(jev.PERSONNEL_FORBIDDEN_SEATS)})) >= 3 \
        else "unconfigured"
