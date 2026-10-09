"""API 集成测试：使用独立的临时 SQLite 文件。"""
import os
import sys
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_TMP = tempfile.mkdtemp(prefix="crc_test_")
os.environ["CRC_DB_PATH"] = str(Path(_TMP) / "test.db")

from app import db  # noqa: E402
from app.main import app  # noqa: E402

db.init_db()
client = TestClient(app)


@pytest.fixture()
def project():
    r = client.post("/api/projects", json={
        "name": "ERP 集成项目", "client_name": "某某集团", "description": "售前澄清"})
    assert r.status_code == 201
    return r.json()


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_requirement_types():
    data = client.get("/api/requirement-types").json()
    assert len(data) == 1
    assert data[0]["type"] == "system_integration"
    assert len(data[0]["fields"]) == 5


def test_project_crud(project):
    pid = project["id"]
    assert any(p["id"] == pid for p in client.get("/api/projects").json())
    detail = client.get(f"/api/projects/{pid}").json()
    assert detail["name"] == "ERP 集成项目"
    assert detail["requirements"] == []
    assert client.delete(f"/api/projects/{pid}").status_code == 200
    assert client.get(f"/api/projects/{pid}").status_code == 404


def test_full_flow_incomplete_to_ready(project):
    pid = project["id"]
    r = client.post(f"/api/projects/{pid}/requirements", json={
        "name": "ERP 系统对接",
        "type": "system_integration",
        "original_request": "希望和现有 ERP 对接。",
        "structured_data": {
            "target_system": "SAP",
            "integration_method": "REST",
            "sync_mode": "定时",
        },
    })
    assert r.status_code == 201
    rid = r.json()["id"]
    assert r.json()["status"] == "incomplete"

    c = client.post(f"/api/requirements/{rid}/check").json()
    assert c["status"] == "incomplete"
    res = c["check_result"]
    assert [f["label"] for f in res["missing_fields"]] == ["系统版本", "认证方式"]
    assert len(res["clarification_questions"]) == 2

    client.patch(f"/api/requirements/{rid}", json={"structured_data": {
        "target_system": "SAP",
        "system_version": "S/4HANA 2023",
        "integration_method": "REST",
        "auth_method": "OAuth2",
        "sync_mode": "定时",
    }})
    c2 = client.post(f"/api/requirements/{rid}/check").json()
    assert c2["status"] == "ready"
    assert c2["check_result"]["missing_fields"] == []
    assert "不代表技术方案一定可行" in c2["check_result"]["notice"]

    # 数据持久化可重新读取
    again = client.get(f"/api/requirements/{rid}").json()
    assert again["structured_data"]["system_version"] == "S/4HANA 2023"
    assert again["status"] == "ready"


def test_patch_only_saves_does_not_change_status(project):
    pid = project["id"]
    rid = client.post(f"/api/projects/{pid}/requirements", json={"name": "D"}).json()["id"]
    client.patch(f"/api/requirements/{rid}", json={"structured_data": {
        "target_system": "SAP", "system_version": "1", "integration_method": "REST",
        "auth_method": "K", "sync_mode": "实时"}})
    assert client.get(f"/api/requirements/{rid}").json()["status"] == "incomplete"
    assert client.post(f"/api/requirements/{rid}/check").json()["status"] == "ready"


def test_invalid_type_rejected(project):
    r = client.post(f"/api/projects/{project['id']}/requirements", json={
        "name": "X", "type": "unknown_type"})
    assert r.status_code == 400
    assert "非法需求类型" in r.json()["detail"]


def test_not_found_errors():
    assert client.get("/api/projects/99999").status_code == 404
    assert client.delete("/api/projects/99999").status_code == 404
    assert client.get("/api/projects/99999/requirements").status_code == 404
    assert client.post("/api/projects/99999/requirements", json={"name": "X"}).status_code == 404
    assert client.get("/api/requirements/99999").status_code == 404
    assert client.patch("/api/requirements/99999", json={"name": "X"}).status_code == 404
    assert client.delete("/api/requirements/99999").status_code == 404
    assert client.post("/api/requirements/99999/check").status_code == 404


def test_delete_requirement(project):
    pid = project["id"]
    rid = client.post(f"/api/projects/{pid}/requirements", json={"name": "D"}).json()["id"]
    assert client.delete(f"/api/requirements/{rid}").status_code == 200
    assert client.get(f"/api/requirements/{rid}").status_code == 404


def test_delete_project_cascades(project):
    pid = project["id"]
    rid = client.post(f"/api/projects/{pid}/requirements", json={"name": "D"}).json()["id"]
    client.delete(f"/api/projects/{pid}")
    assert client.get(f"/api/projects/{pid}").status_code == 404
    assert client.get(f"/api/requirements/{rid}").status_code == 404
    with db.get_connection() as conn:
        orphan = conn.execute(
            "SELECT COUNT(*) c FROM requirements WHERE id = ?", (rid,)
        ).fetchone()["c"]
        assert orphan == 0


def test_static_index_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "客户技术需求澄清工具" in res.text
    assert "需求确认摘要" in res.text
    assert "确认需求" in res.text


# ---------------- 澄清闭环 ----------------

FULL = {
    "target_system": "SAP",
    "system_version": "S/4HANA 2023",
    "integration_method": "REST",
    "auth_method": "OAuth2",
    "sync_mode": "定时",
}


def make_requirement(project, **over):
    payload = {
        "name": "ERP 系统对接",
        "type": "system_integration",
        "original_request": "希望和现有 ERP 对接。",
        "structured_data": {},
    }
    payload.update(over)
    return client.post(f"/api/projects/{project['id']}/requirements", json=payload).json()


def fill(rid, data):
    return client.patch(f"/api/requirements/{rid}", json={"structured_data": data}).json()


def test_incomplete_clarification_items_all_pending(project):
    r = make_requirement(project)
    c = client.post(f"/api/requirements/{r['id']}/check").json()
    items = c["check_result"]["clarification_items"]
    assert len(items) == 5
    assert all(i["status"] == "pending" and i["answer"] == "" for i in items)
    assert len(c["check_result"]["pending_items"]) == 5
    assert c["status"] == "incomplete"


def test_answers_recorded_and_items_confirmed(project):
    r = make_requirement(project, structured_data={
        "target_system": "SAP", "integration_method": "REST", "sync_mode": "定时"})
    rid = r["id"]
    c1 = client.post(f"/api/requirements/{rid}/check").json()
    assert [i["field"] for i in c1["check_result"]["pending_items"]] == \
        ["system_version", "auth_method"]

    fill(rid, FULL)
    c2 = client.post(f"/api/requirements/{rid}/check").json()
    assert c2["status"] == "ready"
    by = {i["field"]: i for i in c2["check_result"]["clarification_items"]}
    assert by["system_version"]["status"] == "confirmed"
    assert by["system_version"]["answer"] == "S/4HANA 2023"
    assert by["auth_method"]["status"] == "confirmed"
    assert by["auth_method"]["answer"] == "OAuth2"
    assert c2["check_result"]["pending_count"] == 0


def test_check_never_auto_confirms(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    c = client.post(f"/api/requirements/{rid}/check").json()
    assert c["status"] == "ready"          # 字段全齐也只到 ready
    assert c["confirmed_at"] is None


def test_manual_confirm_then_summary(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    c = client.post(f"/api/requirements/{rid}/confirm").json()
    assert c["status"] == "confirmed"
    assert c["confirmed_at"] is not None

    s = client.get(f"/api/requirements/{rid}/summary").json()
    assert s["status"] == "confirmed"
    assert s["status_label"] == "已确认"
    assert s["client"] == project["client_name"]
    assert s["requirement_name"] == "ERP 系统对接"
    assert s["original_request"] == "希望和现有 ERP 对接。"
    assert s["pending_count"] == 0
    assert len(s["confirmed_info"]) == 5
    assert "不代表技术方案一定可行" in s["boundary_notice"]


def test_confirm_rejected_when_incomplete(project):
    r = make_requirement(project, structured_data={"target_system": "SAP"})
    res = client.post(f"/api/requirements/{r['id']}/confirm")
    assert res.status_code == 400
    assert "信息不足" in res.json()["detail"]
    assert client.get(f"/api/requirements/{r['id']}").json()["status"] == "incomplete"


def test_confirm_not_found():
    assert client.post("/api/requirements/99999/confirm").status_code == 404


def test_confirmed_rollback_on_core_field_edit(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    assert client.post(f"/api/requirements/{rid}/confirm").json()["status"] == "confirmed"

    # D-1: 清空 system_version -> 自动回退 incomplete，并出现待确认项
    back = fill(rid, {**FULL, "system_version": ""})
    assert back["status"] == "incomplete"
    assert back["confirmed_at"] is None
    by = {i["field"]: i for i in back["check_result"]["clarification_items"]}
    assert by["system_version"]["status"] == "pending"
    assert client.get(f"/api/requirements/{rid}/summary").json()["pending_count"] == 1

    # D-2: 补齐后「保存并检查」-> 恢复 ready（不会自动变 confirmed）
    fill(rid, FULL)
    again = client.post(f"/api/requirements/{rid}/check").json()
    assert again["status"] == "ready"
    assert again["confirmed_at"] is None

    # D-3: 再次人工确认 -> confirmed
    assert client.post(f"/api/requirements/{rid}/confirm").json()["status"] == "confirmed"


def test_confirmed_rollback_to_ready_when_edit_keeps_complete(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    client.post(f"/api/requirements/{rid}/confirm")
    changed = fill(rid, {**FULL, "system_version": "S/4HANA 2023 SP2"})
    assert changed["status"] == "ready"
    assert changed["confirmed_at"] is None


def test_recheck_confirmed_rolls_back(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    client.post(f"/api/requirements/{rid}/confirm")
    # 直接改库模拟脏状态后再检查，应按最新字段回退
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE requirements SET structured_data = ? WHERE id = ?",
            (db.dumps({"target_system": "SAP"}), rid),
        )
    c = client.post(f"/api/requirements/{rid}/check").json()
    assert c["status"] == "incomplete"
    assert c["confirmed_at"] is None


def test_status_cannot_be_written_directly(project):
    r = make_requirement(project, structured_data=FULL)
    res = client.patch(f"/api/requirements/{r['id']}", json={"status": "confirmed"})
    assert res.status_code == 400
    assert client.get(f"/api/requirements/{r['id']}").json()["status"] == "incomplete"


def test_invalid_field_format_rejected(project):
    r = make_requirement(project)
    res = client.patch(
        f"/api/requirements/{r['id']}",
        json={"structured_data": {"system_version": ["not", "a", "string"]}},
    )
    assert res.status_code == 422
    res2 = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"name": "X", "structured_data": "not-an-object"},
    )
    assert res2.status_code == 422


def test_confirmed_data_persists(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    client.post(f"/api/requirements/{rid}/confirm")
    again = client.get(f"/api/requirements/{rid}").json()
    assert again["status"] == "confirmed"
    # 规范化后会附带 *_source 键（无来源时为空串）
    assert {k: v for k, v in again["structured_data"].items() if not k.endswith("_source")} == FULL
    assert again["structured_data"]["system_version_source"] == ""
    assert again["check_result"]["clarification_items"][1]["answer"] == "S/4HANA 2023"
    reqs = client.get(f"/api/projects/{project['id']}/requirements").json()
    assert [x["id"] for x in reqs] == [rid]


def test_delete_project_cascades_confirmed_requirement(project):
    r = make_requirement(project, structured_data=FULL)
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    client.post(f"/api/requirements/{rid}/confirm")
    client.delete(f"/api/projects/{project['id']}")
    assert client.get(f"/api/requirements/{rid}").status_code == 404
    assert client.get(f"/api/requirements/{rid}/summary").status_code == 404
    with db.get_connection() as conn:
        assert conn.execute(
            "SELECT COUNT(*) c FROM requirements WHERE id = ?", (rid,)
        ).fetchone()["c"] == 0


# ---------------- 信息来源 ----------------

def src():
    return {
        "target_system": "SAP", "target_system_source": "customer",
        "system_version": "S/4HANA 2023", "system_version_source": "customer",
        "integration_method": "REST API", "integration_method_source": "internal_document",
        "auth_method": "OAuth2", "auth_method_source": "customer",
        "sync_mode": "定时同步", "sync_mode_source": "sales_inference",
    }


def test_sources_endpoint_lists_three_options():
    data = client.get("/api/sources").json()
    assert [s["value"] for s in data] == ["customer", "internal_document", "sales_inference"]
    assert client.get("/api/requirement-types").json()[0]["sources"] == data


def test_source_saved_per_field(project):
    r = make_requirement(project, structured_data=src())
    d = r["structured_data"]
    assert d["target_system_source"] == "customer"
    assert d["integration_method_source"] == "internal_document"
    assert d["sync_mode_source"] == "sales_inference"


def test_clearing_value_clears_source(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    cleared = fill(rid, {**src(), "system_version": "", "system_version_source": "customer"})
    assert cleared["structured_data"]["system_version"] == ""
    assert cleared["structured_data"]["system_version_source"] == ""


def test_changing_value_invalidates_old_source(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    # 只改值、不带来源 -> 旧来源不得保留
    changed = fill(rid, {"system_version": "S/4HANA 2024"})
    assert changed["structured_data"]["system_version"] == "S/4HANA 2024"
    assert changed["structured_data"]["system_version_source"] == ""
    # 未受影响的字段来源保留
    assert changed["structured_data"]["auth_method_source"] == "customer"


def test_changing_value_with_explicit_source_keeps_it(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    changed = fill(rid, {
        "system_version": "S/4HANA 2024",
        "system_version_source": "internal_document",
    })
    assert changed["structured_data"]["system_version_source"] == "internal_document"


def test_source_only_change_does_not_clear_status(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    client.post(f"/api/requirements/{rid}/confirm")
    same = fill(rid, {**src(), "auth_method_source": "sales_inference"})
    # 值未变 -> 来源可调整，且不需要重新确认
    assert same["status"] == "confirmed"
    assert same["structured_data"]["auth_method_source"] == "sales_inference"


def test_invalid_source_rejected(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    res = client.patch(
        f"/api/requirements/{rid}",
        json={"structured_data": {"system_version": "x", "system_version_source": "unknown"}},
    )
    assert res.status_code == 400
    assert "非法信息来源" in res.json()["detail"]
    # 拒绝后原数据未被破坏
    assert client.get(f"/api/requirements/{rid}").json()["structured_data"][
        "system_version_source"] == "customer"

    res2 = client.post(
        f"/api/projects/{project['id']}/requirements",
        json={"name": "X", "structured_data": {
            "target_system": "SAP", "target_system_source": "gossip"}},
    )
    assert res2.status_code == 400


def test_readiness_unaffected_by_missing_source(project):
    r = make_requirement(project, structured_data=FULL)   # 无任何 source
    rid = r["id"]
    c = client.post(f"/api/requirements/{rid}/check").json()
    assert c["status"] == "ready"
    assert c["check_result"]["missing_fields"] == []
    assert c["check_result"]["source_summary"]["without_source"] == 5
    assert len(c["check_result"]["source_missing_labels"]) == 5
    # 依然只能人工确认
    assert client.post(f"/api/requirements/{rid}/confirm").json()["status"] == "confirmed"


def test_summary_and_recheck_expose_source(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    client.post(f"/api/requirements/{rid}/confirm")
    s = client.get(f"/api/requirements/{rid}/summary").json()
    by = {i["label"]: i for i in s["confirmed_info"]}
    assert by["系统版本"]["source_label"] == "客户确认"
    assert by["接口方式"]["source_label"] == "内部资料"
    assert by["数据同步方式"]["source_label"] == "售前整理"
    counts = {c["source"]: c["count"] for c in s["source_summary"]["counts"]}
    assert counts == {"customer": 3, "internal_document": 1, "sales_inference": 1}
    assert "不代表技术方案已经验证" in s["source_notice"]
    assert "不代表技术方案一定可行" in s["boundary_notice"]


def test_confirmed_edit_value_rolls_back_and_invalidates_source(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    client.post(f"/api/requirements/{rid}/check")
    assert client.post(f"/api/requirements/{rid}/confirm").json()["status"] == "confirmed"

    back = fill(rid, {"system_version": "S/4HANA 2024"})   # 改值，不带来源
    assert back["status"] == "ready"
    assert back["confirmed_at"] is None
    assert back["structured_data"]["system_version_source"] == ""

    # 可重新选择来源并重新确认
    again = fill(rid, {"system_version": "S/4HANA 2024",
                       "system_version_source": "customer"})
    assert again["structured_data"]["system_version_source"] == "customer"
    assert again["status"] == "ready"
    assert client.post(f"/api/requirements/{rid}/confirm").json()["status"] == "confirmed"


def test_legacy_data_without_source_readable(project):
    """旧数据：structured_data 只有值，没有 *_source 键。"""
    r = make_requirement(project)
    rid = r["id"]
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE requirements SET structured_data = ? WHERE id = ?",
            (db.dumps({k: v for k, v in FULL.items()}), rid),
        )
    got = client.get(f"/api/requirements/{rid}").json()
    assert got["structured_data"]["system_version"] == "S/4HANA 2023"
    assert "system_version_source" not in got["structured_data"]

    s = client.get(f"/api/requirements/{rid}/summary").json()
    by = {i["label"]: i for i in s["confirmed_info"]}
    assert by["系统版本"]["value"] == "S/4HANA 2023"
    assert by["系统版本"]["source"] is None        # 不伪造来源
    assert s["source_summary"]["with_source"] == 0
    assert s["source_summary"]["without_source"] == 5

    # 可正常编辑并补来源
    edited = fill(rid, {**FULL, "system_version_source": "customer"})
    assert edited["structured_data"]["system_version_source"] == "customer"


def test_delete_project_cascades_source_data(project):
    r = make_requirement(project, structured_data=src())
    rid = r["id"]
    client.delete(f"/api/projects/{project['id']}")
    assert client.get(f"/api/requirements/{rid}").status_code == 404
    with db.get_connection() as conn:
        row = conn.execute("SELECT structured_data FROM requirements WHERE id = ?",
                           (rid,)).fetchone()
        assert row is None