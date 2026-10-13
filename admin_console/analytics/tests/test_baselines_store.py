import datetime as dt
import json
import threading

from admin_console.analytics import baselines, store, util

from .conftest import NOW


def _resp(person, day, hours):
    ts = dt.datetime.combine(day, dt.time(10), util.CENTRAL)
    return {"person": person, "source": "gmail", "kind": "response", "ts": util.iso(ts),
            "ref": f"t-{day}", "meta": {"hours": hours}}


def test_robust_stats_and_z():
    med, mad, n = baselines.robust_stats([1, 2, 3, 4, 100])
    assert (med, mad, n) == (3, 1, 5)          # the outlier does not move the median/MAD
    z = baselines.robust_z(6, med, mad)
    assert round(z, 2) == round(3 / 1.4826, 2)
    assert baselines.robust_z(None, med, mad) == 0.0


def test_robust_z_floor_on_flat_history():
    assert baselines.robust_z(2.2, 2.0, 0.0) == 2.0      # floor 0.1 scale, not infinity


def test_lately_vs_norm_detects_spike_and_min_samples():
    today = util.central(NOW).date()
    days = [today - dt.timedelta(days=i) for i in range(30, -1, -1) if (today - dt.timedelta(days=i)).weekday() < 5]
    ev = [_resp("a@ntxpllc.com", d, 2.0 + (0.1 if i % 2 else -0.1)) for i, d in enumerate(days[:-2])]
    ev += [_resp("a@ntxpllc.com", d, 8.0) for d in days[-2:]]
    ev += [_resp("b@ntxpllc.com", d, 2.0) for d in days[-4:]]
    out = baselines.compute(ev, NOW)
    a, b = out["a@ntxpllc.com"], out["b@ntxpllc.com"]
    assert a["usable"] and a["z"] > 3.5 and a["latest"] == 8.0
    assert a["recent_days"] == [d.isoformat() for d in days[-2:]]
    assert not b["usable"]                       # 2 history days < MIN_SAMPLES


def test_baselines_saved(isolated):
    store.ensure_schema()
    baselines.save({"a@ntxpllc.com": {"metric": "response_hrs", "median": 2.0, "mad": 0.1, "n": 20,
                                      "latest": 3.0, "z": 6.7}}, NOW)
    row = store.get("Baselines", "a@ntxpllc.com|response_hrs")
    assert row["median"] == 2.0 and row["n"] == 20


def test_json_backend_schema_crud_and_query(isolated):
    created = store.ensure_schema()
    assert set(created) == set(store.SCHEMA)
    assert store.ensure_schema() == []
    for tab in ("SharedContacts", "Runbook"):
        assert tab in store.SCHEMA
    assert store.SCHEMA["SharedContacts"][:14] == ["id", "name", "given", "family", "emails", "phones",
                                                  "org", "title", "address", "notes", "labels",
                                                  "owner_user", "source_ref", "updated"]
    assert store.SCHEMA["Runbook"][:8] == ["id", "workflow", "symptom", "likely_cause", "steps",
                                          "escalate_to", "tier", "updated"]
    fid = store.next_id("Flags", "FL-2026-10-09")
    assert fid == "FL-2026-10-09-001"
    store.append("Flags", {"id": fid, "person": "x@ntxpllc.com", "kpi": "no_shows", "level": 1,
                           "evidence": [{"source": "calendar", "ref": "r", "note": "n"}]})
    assert store.next_id("Flags", "FL-2026-10-09") == "FL-2026-10-09-002"
    store.update("Flags", fid, {"status": "ack"})
    assert store.get("Flags", fid)["status"] == "ack"
    store.upsert("Flags", {"id": fid, "level": 2})
    assert store.get("Flags", fid)["level"] == 2 and store.get("Flags", fid)["status"] == "ack"
    assert store.query("Flags", {"kpi": "no_shows"})[0]["id"] == fid
    assert store.query("Flags", lambda r: r["level"] > 5) == []
    data = json.load(open(isolated / "db.json"))
    assert data["Flags"][0]["evidence"][0]["source"] == "calendar"


def test_single_writer_serializes_concurrent_appends(isolated):
    store.ensure_schema()

    def work(i):
        for j in range(10):
            store.append("ChangeLog", {"id": f"c{i}-{j}", "summary": "x"})
    threads = [threading.Thread(target=work, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(store.rows("ChangeLog")) == 50


def test_sheets_backend_encodes_json_cells():
    calls = []

    class V:
        def __init__(self):
            self.table = [store.SCHEMA["Flags"]]

        def get(self, spreadsheetId, range):  # noqa: A002
            return _Exec({"values": self.table})

        def append(self, **kw):
            calls.append(("append", kw))
            self.table.append(kw["body"]["values"][0])
            return _Exec({})

        def update(self, **kw):
            calls.append(("update", kw))
            return _Exec({})

    class Svc:
        v = V()

        def spreadsheets(self):
            return self

        def values(self):
            return self.v

    b = store.SheetsBackend("sheet123", svc=Svc())
    b.mutate("Flags", lambda rows: rows.append({"id": "F1", "level": 2, "evidence": [{"a": 1}]}))
    assert calls[0][0] == "append"
    line = calls[0][1]["body"]["values"][0]
    assert line[0] == "F1" and json.loads(line[store.SCHEMA["Flags"].index("evidence")]) == [{"a": 1}]
    rows = b.rows("Flags")
    assert rows[0]["evidence"] == [{"a": 1}] and rows[0]["level"] == 2


class _Exec:
    def __init__(self, r):
        self.r = r

    def execute(self):
        return self.r
