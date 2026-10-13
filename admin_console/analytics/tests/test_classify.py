import datetime as dt

from admin_console.analytics import classify, util

from .conftest import NOW

ANGRY = ("This is RIDICULOUS!!! I asked THREE times for the HMS submittals and nothing. "
         "I'm sick of this, I can't keep covering for it. Never again!!")


def ev(person, source, kind, hours_ago, ref="r1", **meta):
    ts = util.as_utc(NOW) - dt.timedelta(hours=hours_ago)
    return {"person": person, "source": source, "kind": kind, "ts": util.iso(ts), "ref": ref, "meta": meta}


def run(events):
    flags, _ = classify.classify(events, NOW, base={}, th=dict(classify.THRESHOLDS))
    return flags


def test_volatility_internal_only():
    s, _ = classify.score_volatility(ANGRY, "maria@ntxpllc.com", ["dana@ntxpllc.com"])
    assert s >= 0.7
    calm, _ = classify.score_volatility("Thanks for the lien waivers, nice work.",
                                        "trevor@ntxpllc.com", ["priya@ntxpllc.com"])
    assert calm < 0.2
    ext, _ = classify.score_volatility(ANGRY, "angry@example.com", ["maria@ntxpllc.com"])
    assert ext is None
    mixed, _ = classify.score_volatility(ANGRY, "maria@ntxpllc.com", ["dana@ntxpllc.com", "gc@example.com"])
    assert mixed is None


def test_external_message_never_flagged_for_volatility():
    flags = run([ev("maria@ntxpllc.com", "gmail", "message", 2, sender="angry@example.com",
                    to=["maria@ntxpllc.com"], internal=False, text=ANGRY)])
    assert flags == []


def test_internal_volatility_is_l3_redflag_with_score():
    flags = run([ev("maria@ntxpllc.com", "gmail", "message", 2, sender="maria@ntxpllc.com",
                    to=["dana@ntxpllc.com"], internal=True, text=ANGRY)])
    (f,) = flags
    assert f["kpi"] == "internal_volatility" and f["level"] == 3 and f["severity"] == "redflag"
    assert 0.7 <= f["volatility"] <= 1.0
    assert all(len(e["note"]) <= 200 for e in f["evidence"])


def test_non_volatility_flags_carry_no_volatility():
    flags = run([ev("j@ntxpllc.com", "calendar", "no_show", 5, title="OAC", attendance="absent", external=False)])
    assert flags[0]["volatility"] is None


def test_minor_deviation_is_l1_note():
    base = {"j@ntxpllc.com": {"usable": True, "z": 2.4, "latest": 4.0, "median": 2.5, "mad": 0.4,
                              "n": 20, "recent_days": ["2026-10-08", "2026-10-09"]}}
    flags, _ = classify.classify([], NOW, base=base, th=dict(classify.THRESHOLDS))
    (f,) = flags
    assert (f["level"], f["severity"], f["urgency"]) == (1, "note", "low")
    base["j@ntxpllc.com"]["usable"] = False
    assert classify.classify([], NOW, base=base, th=dict(classify.THRESHOLDS))[0] == []


def test_external_complaint_l2_then_l3_when_not_forwarded_in_4_business_hours():
    # Friday 10 am CT; complaint at 9 am -> 1 business hour, not forwarded -> L2
    fresh = run([ev("j@ntxpllc.com", "gmail", "complaint", 1, sender="pm@client.org", external=True,
                    phrases=["still waiting"], complaint_type="waiting on response", quote="Still waiting.",
                    forwarded=False, forward_lag_bh=None)])
    assert fresh[0]["level"] == 2 and fresh[0]["severity"] == "redflag" and fresh[0]["urgency"] == "high"
    # Thursday 2 pm -> 5 business hours -> L3
    late = run([ev("j@ntxpllc.com", "gmail", "complaint", 20, sender="pm@client.org", external=True,
                   phrases=["no-show"], complaint_type="no-show", quote="Your super was a no-show.",
                   forwarded=False, forward_lag_bh=None)])
    assert late[0]["level"] == 3
    on_time = run([ev("j@ntxpllc.com", "gmail", "complaint", 20, sender="pm@client.org", external=True,
                      phrases=["no-show"], complaint_type="no-show", quote="x", forwarded=True,
                      forward_lag_bh=1.0)])
    assert on_time[0]["level"] == 2 and on_time[0]["floor_level"] == 2


def test_billing_question_l2_after_one_business_day_l3_after_window():
    q = dict(sender="ap@client.org", subject="Retainage?", answered=False, will_delay_work=False)
    assert run([ev("p@ntxpllc.com", "gmail", "billing_question", 3, **q)]) == []        # < 1 bus. day
    l2 = run([ev("p@ntxpllc.com", "gmail", "billing_question", 24, **q)])               # Thu 10 am
    assert l2[0]["level"] == 2
    l3 = run([ev("p@ntxpllc.com", "gmail", "billing_question", 70, **q)])               # Tue
    assert l3[0]["level"] == 3
    delay = run([ev("p@ntxpllc.com", "gmail", "billing_question", 24, **dict(q, will_delay_work=True))])
    assert delay[0]["level"] == 3 and delay[0]["urgency"] == "critical"
    answered = run([ev("p@ntxpllc.com", "gmail", "billing_question", 70, **dict(q, answered=True))])
    assert answered == []


def test_unanswered_l1_vs_l2():
    one = run([ev("d@ntxpllc.com", "gmail", "unanswered", 30, age_hrs=30, sender="x@client.org", external=True)])
    assert one[0]["level"] == 1
    many = run([ev("d@ntxpllc.com", "gmail", "unanswered", h, ref=f"t{h}", age_hrs=h, sender="x@client.org",
                   external=True) for h in (30, 50, 60)])
    assert many[0]["level"] == 2 and many[0]["kpi"] == "unanswered_email"


def test_doc_integrity_and_quality_rules():
    flags = run([
        ev("p@ntxpllc.com", "jobtread", "vendor_invoice", 5, ref="i1", number="INV-1",
           missing=["po_ref", "amounts do not sum"], amount_ok=False),
        ev("p@ntxpllc.com", "jobtread", "purchase_order", 5, ref="p1", number="PO-1",
           missing=["vendor"], amount_ok=True),
        ev("p@ntxpllc.com", "jobtread", "purchase_order", 5, ref="p2", number="PO-2", missing=[], amount_ok=True),
        ev("d@ntxpllc.com", "jobtread", "daily_log", 5, ref="l1", job="HMS", quality=0.3, issues=["short"],
           has_photos=False),
    ])
    by = {(f["kpi"], f["key"].split("|")[-1]): f for f in flags}
    assert by[("po_invoice_integrity", "i1")]["level"] == 2
    assert by[("po_invoice_integrity", "p1")]["level"] == 1
    assert ("po_invoice_integrity", "p2") not in by
    assert any(f["kpi"] == "daily_report_quality" for f in flags)


def test_confidence_grows_with_evidence_and_agreement():
    low = classify.confidence(1, 1, 5, 2.0)
    high = classify.confidence(4, 3, 25, 6.0)
    assert 0 < low < high <= 0.97


def test_thresholds_are_one_tunable_dict():
    for param, (lo, hi, step, _) in classify.BOUNDS.items():
        assert lo <= classify.THRESHOLDS[param] <= hi and step > 0
    for kpi, param in classify.KPI_PARAM.items():
        assert param in classify.THRESHOLDS
