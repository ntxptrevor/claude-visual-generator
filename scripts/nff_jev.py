#!/usr/bin/env python3
"""
NTXP Form Fill JEV-1 decision layer (contract: .claude/skills/ntxp-form-fill/ARCHITECTURE.md,
section "JEV-1 layer"). Pure Python stdlib.

Public API:
    classify_field(label, page_text_near="", rect=None)            -> {"type", "confidence", "reason"}
    choose_value(field_name, field_type, kb, canonical)              -> {"value", "source", "confidence",
                                                                         "basis", "autofill", ...}
    field_confidence(conn_or_counts, field_name, source_kind, match_score) -> Confidence (a float
                                                                         with .low/.high/.as_dict())
    form_confidence(fields, checks)                                  -> {"score", "low", "high", "drivers"}
    review(session_state, conn=None)                                 -> {"checks", "issues", "confidence"}
    portal_fill_plan(url, answers)                                   -> Playwright step plan (not executed)

Decision order: Tier 1 (CLAUDE.md) -> canonical (nff_canonical.determine) -> KB -> manual.
Prices, signatures, initials, notary/jurat/affidavit blocks, banking values and yes/no legal
certifications are never auto-filled: they always go to the user.

Probability math (documented choices):
  * Field reliability: Beta(1 + accepted, 1 + corrected) from field_outcomes, blended with a
    source prior p0 = SOURCE_RANK[kind] / 100 at prior strength k = 4, i.e. the posterior
    Beta(1 + k*p0 + accepted, 1 + k*(1 - p0) + corrected). Field confidence = its mean x match_score.
  * 90% credible interval: exact 5% / 95% quantiles of that Beta, from the regularized incomplete
    beta function (Lentz continued fraction, Numerical Recipes 6.4) inverted by bisection;
    both bounds are scaled by match_score like the mean.
  * Tier 1 values are rules, not estimates: fixed 0.99 (interval 0.98-1.0) x match_score.
  * Form confidence: geometric mean of filled-field confidences x coverage penalty
    (0.5 + 0.5 x share of required fields filled) x 0.97 per failed non-blocking check;
    any failed blocking check caps score and bounds at 0.5. low/high are the same formula applied
    to the field interval bounds (a conservative envelope, not a joint posterior).

Model referee for ambiguous labels: local Ollama qwen2.5:7b-instruct (3 s timeout) if reachable,
else Claude Haiku if ANTHROPIC_API_KEY is set, else the rule result. Never DeepSeek/GLM.
Network calls go through module-level HTTP_POST, which tests replace.
"""

import json
import math
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from nff_canonical import CONFIDENTIAL_CATEGORIES, SOURCE_RANK, determine, mask, normalize
from nff_signatures import AUTHORIZED_SIGNERS, NTXP_IDENTITY, TIER1_FIELD_OVERRIDES, validate_signer
from nff_workflow_registry import NEVER_AUTOFILL_KB_FIELDS, PRICE_LABEL_RE, SIGNATURE_LABEL_RE

FIELD_TYPES = ("text_word", "text_paragraph", "date", "person", "address", "phone", "email",
               "currency", "checkmark", "x_mark", "initials", "signature", "highlight")

OLLAMA_MODEL = "qwen2.5:7b-instruct"
OLLAMA_TIMEOUT = 3
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-5"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
BLOCKED_MODEL_HOSTS = re.compile(r"(?i)(deepseek|glm|zhipu|bigmodel|chatglm)")
LLM_THRESHOLD = 0.6
PRIOR_STRENGTH = 4.0

# Values JEV adds to the Tier 1 overrides in nff_signatures (W-9 line 3a rule).
TIER1_EXTRA = {
    "tax_classification": "S corporation",
    "w9_tax_classification": "s_corp",
    "tax_classification_box": "s_corp",
    "llc_tax_class_code": "",
}

# Retired NTXP values: never chosen, flagged anywhere they appear.
RETIRED_PATTERNS = [
    (re.compile(r"(?i)\b405\s+S(outh)?\.?\s+Elm\b"), "retired address 405 S Elm St"),
]

NOTARY_RE = re.compile(r"(?i)(notary|notari[sz]ed|jurat|affidavit|sworn|subscribed\s+and\s+sworn|"
                       r"acknowledg(e)?ment\s+before|my\s+commission\s+expires|notary\s+seal|\bseal\b)")
CERTIFICATION_RE = re.compile(
    r"(?i)(debar|suspen(ded|sion)|felon|convict|indict|conflict\s+of\s+interest|boycott|"
    r"\bisrael\b|energy\s+compan|firearm|terroris|lobbying|collusi|non-?collusion|"
    r"anti-?trust|kickback|gratuit|litigation|bankrupt|default(ed)?\s+on|"
    r"criminal|sanction|excluded\s+part|ineligib|certif(y|ies|ication)\b.*\b(yes|no)\b|"
    r"\b(yes|no)\b.*\bcertif)")
BANKING_RE = re.compile(r"(?i)(bank|routing|aba\b|account\s*(number|no|#)|ach\b|swift|iban)")
TAX_ID_RE = re.compile(r"(?i)(\bein\b|\btin\b|tax\s*id|employer\s+identification|ssn|social\s+security)")

# (type, confidence, regex, reason). First match wins; order matters.
_RULES = [
    ("highlight", 0.9, r"\bhighlight", "label asks for a highlight"),
    ("date", 0.92, r"\bdate\b|\bdated\b|mm\s*/\s*dd|\bday\s+of\b|expiration|effective\s+on", "date wording"),
    ("initials", 0.93, r"\binitials?\b|initial\s+here", "initials wording"),
    ("signature", 0.95, r"signature|sign\s*here|^\s*signed\b|\bsigned\s+by\b|^\s*by:?\s*_*\s*$",
     "signature wording"),
    ("email", 0.95, r"e-?\s?mail", "email wording"),
    ("phone", 0.93, r"\bphone\b|telephone|\btel\b|\bfax\b|mobile|\bcell\b", "phone wording"),
    ("x_mark", 0.85, r"mark\s+(an\s+)?[\"']?x\b|place\s+(an\s+)?[\"']?x\b|\bx\s+(in|the)\s+(box|space)|"
     r"indicate\s+with\s+(an\s+)?x", "asks for an X"),
    ("checkmark", 0.85, r"check\s+(one|all|box|if|the|here|applicable)|\byes\s*/\s*no\b|\byes\b.*\bno\b|"
     r"[☐☑□]|\[\s*\]|tick", "check-box wording"),
    ("currency", 0.9, r"amount|dollars|\$|\bprice\b|\bcost\b|\bfee\b|\btotal\b|base\s*bid|lump\s*sum|"
     r"revenue|limit\s+of\s+liability|bond(ing)?\s+(capacity|limit|amount)|aggregate|each\s+occurrence",
     "money wording"),
    ("address", 0.9, r"address|street|\bcity\b|\bzip\b|postal|mailing|p\.?\s?o\.?\s+box", "address wording"),
    ("text_paragraph", 0.85, r"describe|explain|description|comments?|remarks|narrative|scope\s+of|"
     r"\bdetails?\b|experience|qualifications|list\s+(all|any)|if\s+yes", "asks for prose"),
    ("person", 0.85, r"(contact|representative|owner|officer|principal|print(ed)?|signer|agent|person|"
     r"president|manager|attention|attn)\b.*\bname\b|\bname\b.*\b(of\s+)?(contact|representative|owner|"
     r"officer|principal|signer|agent|person)\b|printed\s+name|^\s*name\s*:?\s*$|^\s*attn", "person name wording"),
    ("text_word", 0.75, r"\bname\b|\bnumber\b|\bno\.?\b|\b#|\bein\b|\btin\b|license|title|\bid\b|code|"
     r"naics|duns|\buei\b|county|state\b", "short single-line value"),
]
_RULES = [(t, c, re.compile(p, re.I), r) for t, c, p, r in _RULES]


# --------------------------------------------------------------------------- network

def _urllib_post_json(url, payload, headers=None, timeout=10):
    """POST JSON and return the decoded JSON body. Raises on any failure."""
    if BLOCKED_MODEL_HOSTS.search(url):
        raise PermissionError("DeepSeek/GLM endpoints are never used for NTXP content")
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


HTTP_POST = _urllib_post_json  # replaced in tests; signature (url, payload, headers, timeout)


def _post(url, payload, headers=None, timeout=10):
    if BLOCKED_MODEL_HOSTS.search(url):
        raise PermissionError("DeepSeek/GLM endpoints are never used for NTXP content")
    return HTTP_POST(url, payload, headers, timeout)


def _redact(text):
    """Mask long digit runs (account, routing, EIN, SSN) before text leaves the machine."""
    return re.sub(r"\d[\d\- ]{4,}\d", lambda m: mask(re.sub(r"\D", "", m.group()), "banking"), str(text or ""))


def _parse_json_obj(text):
    m = re.search(r"\{.*\}", text or "", re.S)
    return json.loads(m.group()) if m else None


def _anthropic(model, system, user, max_tokens=512, timeout=30):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return None
    body = _post(ANTHROPIC_URL, {"model": model, "max_tokens": max_tokens, "system": system,
                                 "messages": [{"role": "user", "content": user}]},
                 {"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout)
    text = "".join(b.get("text", "") for b in body.get("content", []) if b.get("type") == "text")
    return _parse_json_obj(text)


_CLASSIFY_SCHEMA = {"type": "object", "required": ["type", "confidence"],
                    "properties": {"type": {"type": "string", "enum": list(FIELD_TYPES)},
                                   "confidence": {"type": "number", "minimum": 0, "maximum": 1}}}
_CLASSIFY_SYSTEM = ("You classify one blank on a US construction bid/compliance form. Reply with JSON "
                    "only, matching this schema: " + json.dumps(_CLASSIFY_SCHEMA) + ". Types: text_word "
                    "(short single-line), text_paragraph (multi-line prose), date, person, address, phone, "
                    "email, currency, checkmark, x_mark, initials, signature, highlight.")


def _llm_classify(label, near, rect):
    """Ollama first, then Claude Haiku. Returns (type, confidence, referee) or None."""
    prompt = json.dumps({"label": _redact(label), "nearby_text": _redact(near)[:600],
                         "box": _rect_wh(rect)})
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
    if not host.startswith("http"):
        host = "http://" + host
    try:
        body = _post(host + "/api/chat", {"model": OLLAMA_MODEL, "stream": False, "format": _CLASSIFY_SCHEMA,
                                          "options": {"temperature": 0},
                                          "messages": [{"role": "system", "content": _CLASSIFY_SYSTEM},
                                                       {"role": "user", "content": prompt}]},
                     None, OLLAMA_TIMEOUT)
        out = _parse_json_obj((body.get("message") or {}).get("content", ""))
        if out and out.get("type") in FIELD_TYPES:
            return out["type"], float(out.get("confidence", 0.6)), "ollama:" + OLLAMA_MODEL
    except Exception:  # noqa: BLE001 - unreachable server is the normal case
        pass
    try:
        out = _anthropic(HAIKU_MODEL, _CLASSIFY_SYSTEM, prompt, max_tokens=100, timeout=15)
        if out and out.get("type") in FIELD_TYPES:
            return out["type"], float(out.get("confidence", 0.6)), "anthropic:" + HAIKU_MODEL
    except Exception:  # noqa: BLE001
        pass
    return None


# --------------------------------------------------------------------------- 1. classify

def _rect_wh(rect):
    """(width, height) from [x0,y0,x1,y1], {x,y,w,h}, {width,height} or {x0,y0,x1,y1}; else None."""
    if not rect:
        return None
    try:
        if isinstance(rect, dict):
            if "w" in rect or "width" in rect:
                return abs(float(rect.get("w", rect.get("width")))), abs(float(rect.get("h", rect.get("height"))))
            x0, y0 = rect.get("x0", rect.get("x1")), rect.get("y0", rect.get("y1"))
            x1, y1 = rect.get("x1" if "x0" in rect else "x2"), rect.get("y1" if "y0" in rect else "y2")
            return abs(float(x1) - float(x0)), abs(float(y1) - float(y0))
        x0, y0, x1, y1 = (float(v) for v in rect)
        return abs(x1 - x0), abs(y1 - y0)
    except (TypeError, ValueError, KeyError):
        return None


def _rule_classify(label, near, rect):
    text = f"{label or ''}"
    wh = _rect_wh(rect)
    if wh:
        w, h = wh
        if 0 < w <= 18 and 0 < h <= 18 and 0.6 <= w / h <= 1.6:
            if re.search(r"(?i)\bx\b", f"{label} {near}") and re.search(r"(?i)mark|place|indicate", f"{label} {near}"):
                return {"type": "x_mark", "confidence": 0.9, "reason": "tiny square box; text asks for an X"}
            return {"type": "checkmark", "confidence": 0.9, "reason": "tiny square box"}
    for ftype, conf, rx, reason in _RULES:
        if rx.search(text):
            if ftype in ("text_word", "person") and wh and wh[1] >= 40 and wh[1] / max(wh[0], 1) > 0.12:
                return {"type": "text_paragraph", "confidence": 0.8, "reason": "tall box; " + reason}
            return {"type": ftype, "confidence": conf, "reason": reason}
    for ftype, conf, rx, reason in _RULES:  # weaker: wording only in nearby text
        if near and rx.search(near):
            return {"type": ftype, "confidence": round(conf * 0.65, 2), "reason": reason + " (nearby text)"}
    if wh and wh[1] >= 40 and wh[1] / max(wh[0], 1) > 0.12:
        return {"type": "text_paragraph", "confidence": 0.7, "reason": "tall box"}
    return {"type": "text_word", "confidence": 0.4, "reason": "no rule matched; default single line"}


def classify_field(label, page_text_near="", rect=None, *, use_llm=True):
    """Classify one form blank into a FIELD_TYPES type. Rules first; model referee below 0.6."""
    result = _rule_classify(label, page_text_near, rect)
    result["referee"] = "rules"
    if use_llm and result["confidence"] < LLM_THRESHOLD:
        got = _llm_classify(label, page_text_near, rect)
        if got:
            ftype, conf, referee = got
            result = {"type": ftype, "confidence": round(max(0.0, min(conf, 0.85)), 2),
                      "reason": f"model referee ({referee}); rules said {result['type']}", "referee": referee}
    return result


# --------------------------------------------------------------------------- 2. choose value

def _tier1_value(field_name):
    if field_name in TIER1_FIELD_OVERRIDES:
        return NTXP_IDENTITY[TIER1_FIELD_OVERRIDES[field_name]]
    if field_name in TIER1_EXTRA:
        return TIER1_EXTRA[field_name]
    return None


def is_retired(value):
    return next((why for rx, why in RETIRED_PATTERNS if value and rx.search(str(value))), None)


def never_autofill_reason(field_name, field_type, label=""):
    """Why a field must go to the user, or None if it may be auto-filled."""
    text = f"{field_name or ''} {label or ''}".replace("_", " ")
    if field_type == "signature" or (SIGNATURE_LABEL_RE.search(text) and "initial" not in text.lower()):
        return "signature - Tier 3 signature step only"
    if field_type == "initials" or re.search(r"(?i)\binitials?\b", text):
        return "initials - signer enters or approves"
    if NOTARY_RE.search(text):
        return "notary / jurat / affidavit block - notary and signer complete it"
    if CERTIFICATION_RE.search(text):
        return "yes/no legal certification - the owner answers it"
    if field_type == "currency" or field_name in NEVER_AUTOFILL_KB_FIELDS or PRICE_LABEL_RE.search(text):
        return "price or money commitment - owner enters it"
    if BANKING_RE.search(text):
        return "banking value - Tier 3 approval to fill"
    return None


def _canonical_lookup(field_name, canonical, category):
    """Normalize the many shapes canonical may take into a determine()-style decision or None."""
    if not canonical or field_name not in canonical:
        return None
    entry = canonical[field_name]
    if isinstance(entry, list):
        return determine(field_name, entry, category)
    if isinstance(entry, dict) and "status" in entry:
        return entry
    if isinstance(entry, dict):
        return determine(field_name, [entry], category)
    if entry in (None, ""):
        return None
    return {"value": entry, "status": "canonical", "basis": "canonical answer", "source_kind": "owner_canonical"}


def _category_for(field_name, label=""):
    text = f"{field_name} {label}"
    if BANKING_RE.search(text):
        return "banking"
    if TAX_ID_RE.search(text):
        return "tax_id"
    return "other"


def choose_value(field_name, field_type, kb, canonical, *, label="", category=None, counts=None):
    """Deterministic value choice: Tier 1 -> canonical -> KB -> manual.

    Returns {"value", "source", "confidence", "basis", "autofill", "suggested"}. When autofill is
    False, value is None and the user enters the field; "suggested" may hold a non-price default
    (e.g. the designated signer's name for a signature block) for the GUI to offer.
    counts: optional conn / counts_fn passed to field_confidence for learned reliability.
    """
    category = category or _category_for(field_name, label)
    hold = never_autofill_reason(field_name, field_type, label)
    if hold:
        suggested = None
        if field_type in ("signature", "initials") or hold.startswith(("signature", "initials")):
            signer = NTXP_IDENTITY["designated_signatory"]
            suggested = signer if field_type != "initials" and not hold.startswith("initials") else \
                "".join(p[0] for p in signer.split())
        return {"value": None, "source": "manual", "confidence": 0.0, "basis": hold,
                "autofill": False, "suggested": suggested}

    t1 = _tier1_value(field_name)
    if t1 is not None:
        conf = field_confidence(counts, field_name, "tier1", 1.0)
        return {"value": t1, "source": "tier1", "confidence": float(conf), "low": conf.low, "high": conf.high,
                "basis": "Tier 1 rule (CLAUDE.md)", "autofill": True, "suggested": None}

    dec = _canonical_lookup(field_name, canonical, category)
    if dec and dec.get("status") in ("conflict", "missing"):
        return {"value": None, "source": "manual", "confidence": 0.0,
                "basis": "canonical: " + dec.get("basis", dec["status"]), "autofill": False, "suggested": None}
    if dec and dec.get("value") not in (None, "") and not is_retired(dec["value"]):
        kind = dec.get("source_kind") or _kind_from_basis(dec.get("basis", "")) or "owner_canonical"
        conf = field_confidence(counts, field_name, kind, 0.9 if dec.get("status") == "stale" else 1.0)
        autofill = category not in CONFIDENTIAL_CATEGORIES or category == "tax_id"
        return {"value": dec["value"], "source": "canonical", "confidence": float(conf), "low": conf.low,
                "high": conf.high, "basis": dec.get("basis", "canonical answer")
                + (" (stale - confirm)" if dec.get("status") == "stale" else ""),
                "autofill": autofill, "suggested": None}

    kb_val = (kb or {}).get(field_name)
    if kb_val not in (None, ""):
        why = is_retired(kb_val)
        if why:
            return {"value": None, "source": "manual", "confidence": 0.0,
                    "basis": f"KB value is a {why}; owner must supply", "autofill": False, "suggested": None}
        conf = field_confidence(counts, field_name, "kb_manual", 1.0)
        return {"value": str(kb_val), "source": "kb", "confidence": float(conf), "low": conf.low,
                "high": conf.high, "basis": "KB value", "autofill": True, "suggested": None}

    return {"value": None, "source": "manual", "confidence": 0.0, "basis": "no Tier 1, canonical or KB value",
            "autofill": False, "suggested": None}


def _kind_from_basis(basis):
    k = (basis or "").split(":", 1)[0].strip()
    return k if k in SOURCE_RANK else None


# --------------------------------------------------------------------------- 3. probabilities

def _betacf(a, b, x, max_iter=300, eps=3e-14):
    """Continued fraction for the incomplete beta (modified Lentz, Numerical Recipes 6.4)."""
    tiny = 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    d = 1.0 / (d if abs(d) > tiny else tiny)
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        d = 1.0 / (d if abs(d) > tiny else tiny)
        c = 1.0 + aa / c
        c = c if abs(c) > tiny else tiny
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            break
    return h


def beta_cdf(x, a, b):
    """Regularized incomplete beta I_x(a, b)."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_front = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    if x < (a + 1.0) / (a + b + 2.0):
        return math.exp(ln_front) * _betacf(a, b, x) / a
    return 1.0 - math.exp(ln_front) * _betacf(b, a, 1.0 - x) / b


def beta_quantile(p, a, b, tol=1e-10):
    """Inverse of beta_cdf by bisection (monotone, always converges)."""
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if beta_cdf(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            break
    return (lo + hi) / 2


class Confidence(float):
    """A float (the confidence) carrying .low/.high (90% interval) and the Beta parameters."""

    def __new__(cls, value, low, high, **details):
        obj = super().__new__(cls, value)
        obj.low, obj.high, obj.details = low, high, details
        return obj

    def as_dict(self):
        return {"confidence": float(self), "low": self.low, "high": self.high, **self.details}


SOURCE_ALIASES = {"canonical": "owner_canonical", "kb": "kb_manual", "manual": "kb_manual",
                  "derived": "company_doc", "scan": "drive_scan"}
USER_PRIOR = 0.95  # value the user typed or confirmed in the GUI


def _source_prior(source_kind):
    if source_kind in ("user", "user_entered"):
        return USER_PRIOR
    kind = SOURCE_ALIASES.get(source_kind, source_kind)
    return min(SOURCE_RANK.get(kind, 30), 99) / 100.0


def _counts(conn_or_counts, field_name):
    src = conn_or_counts
    if src is None:
        return 0, 0
    if isinstance(src, (tuple, list)) and len(src) == 2:
        return int(src[0]), int(src[1])
    if isinstance(src, dict):
        got = src.get(field_name, (0, 0))
        return int(got[0]), int(got[1])
    if callable(src) and not hasattr(src, "execute"):
        a, c = src(field_name)
        return int(a), int(c)
    import nff_db  # lazy: owned by another module; only needed with a live connection
    a, c = nff_db.outcome_counts(src, field_name)
    return int(a), int(c)


def field_confidence(conn_or_counts, field_name, source_kind, match_score=1.0):
    """Learned per-field reliability x match score, with a 90% credible interval.

    conn_or_counts: sqlite3 connection (uses nff_db.outcome_counts), a counts_fn(field_name) ->
    (accepted, corrected), a (accepted, corrected) tuple, a {field: (a, c)} dict, or None.
    Returns a Confidence float; .low/.high are the 5%/95% Beta quantiles x match_score.
    """
    m = max(0.0, min(1.0, float(match_score)))
    accepted, corrected = _counts(conn_or_counts, field_name)
    post_a, post_b = 1.0 + accepted, 1.0 + corrected
    if SOURCE_ALIASES.get(source_kind, source_kind) == "tier1":
        return Confidence(round(0.99 * m, 4), round(0.98 * m, 4), round(1.0 * m, 4), alpha=None, beta=None,
                          prior=1.0, accepted=accepted, corrected=corrected, source_kind="tier1",
                          posterior_mean=post_a / (post_a + post_b), basis="Tier 1 rule")
    p0 = _source_prior(source_kind)
    a = post_a + PRIOR_STRENGTH * p0
    b = post_b + PRIOR_STRENGTH * (1.0 - p0)
    mean = a / (a + b)
    return Confidence(round(mean * m, 4), round(beta_quantile(0.05, a, b) * m, 4),
                      round(beta_quantile(0.95, a, b) * m, 4), alpha=a, beta=b, prior=p0,
                      accepted=accepted, corrected=corrected, source_kind=source_kind,
                      posterior_mean=post_a / (post_a + post_b), basis="Beta posterior + source prior")


def form_confidence(fields, checks):
    """Overall confidence for the filled form.

    Shown to the user in the GUI only. It must never be printed on the document.

    fields: [{"name"/"label", "value", "confidence", "low"?, "high"?, "required"?}]
    checks: [{"id", "passed", "blocking", "message", "advisory"?}]
    """
    fields, checks = fields or [], checks or []
    filled = [f for f in fields if str(f.get("value") or "").strip()
              and not (f.get("radio_group") and not _checked(f.get("value")))]
    # A required radio group is one unit, satisfied by any selected option.
    picked_groups = {f.get("radio_group") for f in fields
                     if f.get("radio_group") and _checked(f.get("value"))}
    required, seen_groups = [], set()
    for f in fields:
        if not f.get("required"):
            continue
        group = f.get("radio_group")
        if not group:
            required.append(f)
        elif group not in seen_groups:
            seen_groups.add(group)
            required.append({"name": group, "label": f.get("label") or group,
                             "value": "chosen" if group in picked_groups else ""})
    blank_req = [f for f in required if not str(f.get("value") or "").strip()]

    def gmean(vals):
        vals = [max(1e-6, float(v)) for v in vals]
        return math.exp(sum(math.log(v) for v in vals) / len(vals)) if vals else 0.0

    confs = [float(f.get("confidence") or 0.0) for f in filled]
    lows = [float(f.get("low", f.get("confidence") or 0.0)) for f in filled]
    highs = [float(f.get("high", f.get("confidence") or 0.0)) for f in filled]
    coverage = 0.5 + 0.5 * ((len(required) - len(blank_req)) / len(required)) if required else 1.0
    real = [c for c in checks if not c.get("advisory")]
    failed = [c for c in real if not c.get("passed")]
    blocking = [c for c in failed if c.get("blocking")]
    soft = 0.97 ** (len(failed) - len(blocking))
    factor = coverage * soft
    score, low, high = gmean(confs) * factor, gmean(lows) * factor, gmean(highs) * factor
    if blocking:
        score, low, high = min(score, 0.5), min(low, 0.5), min(high, 0.5)

    drivers = []
    for f in sorted(filled, key=lambda f: float(f.get("confidence") or 0.0))[:3]:
        drivers.append(f"Low confidence: {f.get('label') or f.get('name')} at "
                       f"{round(100 * float(f.get('confidence') or 0))}% (source: {f.get('source', 'unknown')})")
    for f in blank_req:
        drivers.append(f"Required field left blank: {f.get('label') or f.get('name')}")
    for c in failed:
        drivers.append(("Blocking: " if c.get("blocking") else "Check failed: ") + c.get("message", c.get("id", "")))
    return {"score": round(score, 4), "low": round(min(low, score), 4), "high": round(max(high, score), 4),
            "drivers": drivers, "filled": len(filled), "required_blank": len(blank_req),
            "blocking_failures": len(blocking)}


# --------------------------------------------------------------------------- 5. review

_FORMAT_RE = {
    "date": (re.compile(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/\d{4}$"), "date must be MM/DD/YYYY"),
    "phone": (re.compile(r"^(\(\d{3}\) \d{3}-\d{4}|\d{3}-\d{3}-\d{4})$"), "phone must be (###) ###-#### or ###-###-####"),
    "email": (re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$"), "invalid email address"),
    "ein": (re.compile(r"^\d{2}-?\d{7}$"), "EIN must be ##-#######"),
    "currency": (re.compile(r"^\(?\$\d{1,3}(,\d{3})*(\.\d{2})?\)?$"), "currency must look like $1,234.00"),
}


def _fname(f):
    return f.get("kb_field") or f.get("field_name") or f.get("name") or f.get("id") or ""


def _flabel(f):
    return f.get("label") or f.get("field_name_raw") or _fname(f)


def _is_user(f):
    return bool(f.get("user_entered")) or f.get("source") in ("user", "user_entered", "manual_entry")


def _checked(v):
    return str(v or "").strip().lower() not in ("", "off", "/off", "false", "0", "no", "none")


def _check(checks, cid, passed, blocking, message):
    checks.append({"id": cid, "passed": bool(passed), "blocking": bool(blocking), "message": message})


def _approval_ok(state, signer_value):
    approvals = state.get("approvals") or ([state["signature_approval"]] if state.get("signature_approval") else [])
    for ap in approvals:
        if not ap or ap.get("decision") != "approve" or not ap.get("request_id") or not ap.get("approved_by"):
            continue
        v = validate_signer(ap.get("signer", ""))
        if not v["authorized"] or (signer_value and normalize(ap.get("signer")) not in normalize(signer_value)):
            continue
        if v["signer"]["requires_circumstance"] and not (ap.get("circumstance") or "").strip():
            continue
        doc = state.get("document_path")
        if doc and ap.get("document_sha256") and Path(doc).exists():
            from nff_signatures import document_digest
            if document_digest(doc) != ap["document_sha256"]:
                continue
        return True
    return False


def _session_dir(state):
    if state.get("session_dir"):
        return Path(state["session_dir"])
    home = Path(os.environ.get("NFF_HOME", Path.home() / ".ntxp" / "nff"))
    return home / "sessions" / str(state.get("session_id") or "_adhoc")


def review_packet(state, fields, checks):
    """Masked packet for the AI review: labels + values; banking and tax-ID values masked."""
    def safe(f):
        cat = _category_for(_fname(f), _flabel(f))
        return {"field": _fname(f), "label": _flabel(f), "type": f.get("type"),
                "value": mask(f.get("value") or "", cat) if cat in CONFIDENTIAL_CATEGORIES else f.get("value"),
                "source": f.get("source")}
    canon = {k: (mask(v, _category_for(k)) if _category_for(k) in CONFIDENTIAL_CATEGORIES else v)
             for k, v in (state.get("canonical") or {}).items() if not isinstance(v, (dict, list))}
    return {"session_id": state.get("session_id"), "form_type": state.get("form_type"),
            "fields": [safe(f) for f in fields], "historical_answers": canon,
            "deterministic_failures": [c for c in checks if not c["passed"]],
            "instructions": "Find interpretation errors: values that answer a different question than the "
                            "label asks, or that disagree with historical answers. Advisory only; do not "
                            "propose prices, signatures or certification answers."}


_REVIEW_SYSTEM = ("You review a filled construction-company form. Reply with JSON only: "
                  '{"advisories": [{"field": str, "message": str}]}. Report interpretation errors and '
                  "disagreements with historical answers. Never suggest prices, signatures or legal answers.")


def review(session_state, conn=None, *, ai=True):
    """Deterministic compliance checks on a completed form, plus an optional AI advisory pass.

    session_state: {"session_id", "session_dir"?, "form_type", "fields": [{"id", "kb_field"/"name",
    "label", "type", "value", "required", "source", "user_entered", "confidence"?, "match_score"?}],
    "approvals"/"signature_approval", "canonical": {field: value}, "retired": [str], "signer"?,
    "document_path"?}. Returns {"checks", "issues", "advisories", "confidence"}.
    """
    state = session_state or {}
    fields = state.get("fields") or []
    checks = []
    form_type = (state.get("form_type") or "").lower()

    # Tier 1 identity
    for f in fields:
        name, val = _fname(f), str(f.get("value") or "").strip()
        want = _tier1_value(name)
        if want is None or not val or name in ("signer_name",):
            continue
        if name in ("phone",):
            ok = re.sub(r"\D", "", val)[-10:] == re.sub(r"\D", "", want)
        else:
            ok = normalize(val) == normalize(want)
        _check(checks, f"tier1.{name}", ok, True,
               f"{_flabel(f)} is '{val}'; Tier 1 requires '{want}'" if not ok else f"{_flabel(f)} matches Tier 1")

    # Signer
    signer_vals = [str(f.get("value")).strip() for f in fields
                   if _fname(f) in ("signer_name", "signatory", "printed_name") and f.get("value")]
    if state.get("signer"):
        signer_vals.append(str(state["signer"]).strip())
    for sv in signer_vals:
        v = validate_signer(sv)
        if not v["authorized"]:
            _check(checks, "tier1.signer", False, True,
                   f"Signer '{sv}' is not authorized; designated signatory is {NTXP_IDENTITY['designated_signatory']}")
        elif v["signer"]["requires_circumstance"]:
            circ = any((ap or {}).get("circumstance") for ap in
                       (state.get("approvals") or [state.get("signature_approval")]))
            _check(checks, "tier1.signer", bool(circ), True,
                   f"{sv} is the alternate signatory; state the circumstance or use "
                   f"{NTXP_IDENTITY['designated_signatory']}" if not circ else f"{sv} signs with a stated circumstance")
        else:
            _check(checks, "tier1.signer", True, True, f"Signer {sv} is the designated signatory")

    # W-9 line 3a
    if form_type == "w9" or any(_fname(f).startswith("c1_1") for f in fields):
        by = {_fname(f): f.get("value") for f in fields}
        llc_box = _checked(by.get("c1_1[5]")) or "llc" in str(by.get("tax_classification", "")).lower()
        llc_code = str(by.get("f1_03[0]") or by.get("llc_tax_class_code") or "").strip()
        s_corp = (str(by.get("c1_1[2]", "")).strip() == "/3"
                  or re.search(r"(?i)s[\s_-]*corp", str(by.get("tax_classification", "")) +
                               str(by.get("tax_classification_box", "")) + str(by.get("w9_tax_classification", ""))))
        others = [k for k in ("c1_1[0]", "c1_1[1]", "c1_1[3]", "c1_1[4]", "c1_1[6]") if _checked(by.get(k))]
        ok = bool(s_corp) and not llc_box and not llc_code and not others
        _check(checks, "tier1.w9_scorp", ok, True,
               "W-9 line 3a: S corporation only checked; LLC box and LLC code blank" if ok else
               "W-9 line 3a must check S corporation only (no LLC box, LLC code blank)")

    # Retired values anywhere
    extra = [re.compile(re.escape(r), re.I) for r in state.get("retired") or [] if r]
    for f in fields:
        val = str(f.get("value") or "")
        why = is_retired(val) or next((f"retired value '{rx.pattern}'" for rx in extra if rx.search(val)), None)
        if why:
            _check(checks, f"retired.{_fname(f)}", False, True, f"{_flabel(f)} contains a {why}")
    if not any(c["id"].startswith("retired.") for c in checks):
        _check(checks, "retired.none", True, True, "No retired NTXP values found")

    # Required blanks. A required radio group is satisfied by choosing any one of its options.
    chosen_groups = {f.get("radio_group") for f in fields
                     if f.get("radio_group") and _checked(f.get("value"))}
    reported_groups = set()
    for f in fields:
        if not f.get("required"):
            continue
        group = f.get("radio_group")
        if group:
            if group not in chosen_groups and group not in reported_groups:
                reported_groups.add(group)
                _check(checks, f"required.radio.{group}", False, True, f"Required choice '{group}' has no option selected")
            continue
        if str(f.get("value") or "").strip():
            continue
        _check(checks, f"required.{_fname(f)}", False, True, f"Required field '{_flabel(f)}' is blank")

    # Formats
    for f in fields:
        val = str(f.get("value") or "").strip()
        if not val:
            continue
        name, ftype = _fname(f), f.get("type")
        kind = "ein" if re.search(r"(?i)^ein$|employer identification", f"{name} {_flabel(f)}") else ftype
        if kind in _FORMAT_RE and kind not in ("signature",):
            rx, msg = _FORMAT_RE[kind]
            if not rx.match(val):
                _check(checks, f"format.{name}", False, kind == "ein", f"{_flabel(f)}: {msg} (got '{mask(val, _category_for(name))}')")

    # Signatures need an approval record
    for f in fields:
        if f.get("type") in ("signature", "initials") and str(f.get("value") or "").strip():
            ok = _approval_ok(state, None if f.get("type") == "initials" else str(f.get("value")))
            _check(checks, f"signature.{_fname(f)}", ok, True,
                   f"{_flabel(f)} is signed with a matching Tier 3 approval" if ok else
                   f"{_flabel(f)} has a signature but no matching Tier 3 approval record")

    # Prices / certifications / notary values must be user-entered
    for f in fields:
        if not str(f.get("value") or "").strip() or f.get("type") in ("signature", "initials"):
            continue
        hold = never_autofill_reason(_fname(f), f.get("type"), _flabel(f))
        if hold and not _is_user(f) and not hold.startswith("banking"):
            _check(checks, f"user_only.{_fname(f)}", False, True,
                   f"{_flabel(f)} was filled automatically but is a {hold.split(' - ')[0]}; the owner must enter it")

    # Contradictions with canonical answers
    for f in fields:
        name, val = _fname(f), str(f.get("value") or "").strip()
        canon = (state.get("canonical") or {}).get(name)
        if isinstance(canon, dict):
            canon = canon.get("value")
        if val and canon not in (None, "") and not isinstance(canon, list) and normalize(val) != normalize(canon):
            cat = _category_for(name)
            _check(checks, f"canonical.{name}", False, False,
                   f"{_flabel(f)} '{mask(val, cat)}' differs from the canonical answer '{mask(canon, cat)}'")

    # Field confidences for the form score
    scored = []
    for f in fields:
        g = dict(f, name=_fname(f), label=_flabel(f))
        if str(f.get("value") or "").strip() and f.get("confidence") is None:
            src = "user" if _is_user(f) else (f.get("source_kind") or f.get("source") or "kb_manual")
            c = field_confidence(conn, _fname(f), src, f.get("match_score", 1.0))
            g.update(confidence=float(c), low=c.low, high=c.high)
        scored.append(g)

    advisories = []
    packet = review_packet(state, fields, checks)
    if ai and os.environ.get("ANTHROPIC_API_KEY"):
        try:
            out = _anthropic(SONNET_MODEL, _REVIEW_SYSTEM, json.dumps(packet), max_tokens=1500, timeout=60) or {}
            for i, a in enumerate(out.get("advisories") or []):
                advisories.append({"id": f"ai_review.{i + 1}", "passed": False, "blocking": False, "advisory": True,
                                   "message": f"AI review ({a.get('field', 'form')}): {a.get('message', '')}"})
        except Exception as e:  # noqa: BLE001
            advisories.append({"id": "ai_review.error", "passed": True, "blocking": False, "advisory": True,
                               "message": f"AI review unavailable ({type(e).__name__}); deterministic checks only"})
    elif ai:
        path = _session_dir(state) / "review_packet.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(packet, indent=2, default=str))
        except OSError:
            path = None
        advisories.append({"id": "ai_review.queued", "passed": True, "blocking": False, "advisory": True,
                           "message": "AI review queued for the Claude session", "packet_path": str(path) if path else None})
    checks.extend(advisories)

    issues = [c["message"] for c in checks if not c["passed"]]
    return {"checks": checks, "issues": issues, "advisories": [a["message"] for a in advisories],
            "confidence": form_confidence(scored, checks)}


# --------------------------------------------------------------------------- 6. browser plan

_SUBMIT_RE = re.compile(r"(?i)(submit|send|finali[sz]e|certify|sign\s+and|place\s+bid|confirm\s+bid)")


def portal_fill_plan(url, answers):
    """Playwright step plan for a portal form. Nothing is executed here.

    answers: {selector: value} or [{"selector", "value", "label"?, "type"?, "action"?}].
    Price/signature/certification steps carry no value (the user types them); any submit step is
    Tier 3 and needs explicit owner approval before it runs.
    """
    items = [{"selector": k, "value": v} for k, v in answers.items()] if isinstance(answers, dict) else list(answers or [])
    steps = [{"action": "goto", "url": url, "tier": 0}]
    for a in items:
        sel, label = a.get("selector", ""), a.get("label", "")
        action = a.get("action") or ("click" if a.get("type") in ("checkmark", "x_mark") else "fill")
        if action == "click" and _SUBMIT_RE.search(f"{sel} {label} {a.get('value', '')}") or action == "submit":
            steps.append({"action": "click", "selector": sel, "tier": 3, "requires_approval": True,
                          "note": "submit - Tier 3: explicit owner approval before it runs"})
            continue
        hold = never_autofill_reason(a.get("field_name", ""), a.get("type"), f"{label} {sel}")
        if hold:
            steps.append({"action": "pause_for_user", "selector": sel, "tier": 3 if "signature" in hold else 2,
                          "note": hold})
            continue
        steps.append({"action": action, "selector": sel, "value": None if action == "click" else a.get("value"),
                      "tier": 0})
    return {"url": url, "engine": "playwright", "executed": False, "steps": steps,
            "tier3_steps": [i for i, s in enumerate(steps) if s["tier"] == 3]}


if __name__ == "__main__":
    import sys
    data = json.load(open(sys.argv[1])) if len(sys.argv) > 1 else {}
    print(json.dumps(review(data), indent=2, default=str))
