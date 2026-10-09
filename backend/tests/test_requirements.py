"""检查逻辑单元测试（纯函数，不依赖数据库 / 前端）。"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.requirements import (  # noqa: E402
    BOUNDARY_NOTICE,
    CLARIFICATION_CONFIRMED,
    CLARIFICATION_PENDING,
    STATUS_CONFIRMED,
    STATUS_INCOMPLETE,
    STATUS_READY,
    TYPE_SYSTEM_INTEGRATION,
    UnknownRequirementStatus,
    UnknownRequirementType,
    InvalidSourceError,
    build_clarification_items,
    build_confirmation_summary,
    check_requirement,
    get_field_entries,
    normalize_structured_data,
    summarize_sources,
)

T = TYPE_SYSTEM_INTEGRATION
FULL = {
    "target_system": "SAP",
    "system_version": "S/4HANA 2023",
    "integration_method": "REST",
    "auth_method": "OAuth2",
    "sync_mode": "定时",
}


# ---------------- 澄清项 ----------------

def test_clarification_items_initial_all_pending():
    items = build_clarification_items(T, {})
    assert len(items) == 5
    assert all(i["status"] == CLARIFICATION_PENDING for i in items)
    assert all(i["answer"] == "" for i in items)
    assert items[0] == {
        "field": "target_system",
        "label": "目标系统名称",
        "question": "需要对接的目标系统（产品名称）是什么？",
        "status": CLARIFICATION_PENDING,
        "answer": "",
    }


def test_clarification_item_confirmed_with_answer():
    items = build_clarification_items(T, FULL)
    assert all(i["status"] == CLARIFICATION_CONFIRMED for i in items)
    by_field = {i["field"]: i for i in items}
    assert by_field["system_version"]["answer"] == "S/4HANA 2023"
    assert by_field["auth_method"]["answer"] == "OAuth2"


def test_clarification_item_reverts_to_pending_when_field_cleared():
    filled = build_clarification_items(T, FULL)
    cleared = build_clarification_items(T, {**FULL, "system_version": ""})
    assert by(filled, "system_version")["status"] == CLARIFICATION_CONFIRMED
    assert by(cleared, "system_version")["status"] == CLARIFICATION_PENDING
    assert by(cleared, "system_version")["answer"] == ""


def by(items, field):
    return next(i for i in items if i["field"] == field)


def test_check_never_returns_confirmed():
    r = check_requirement(T, FULL)
    assert r["status"] == STATUS_READY
    assert r["status"] != STATUS_CONFIRMED
    assert "不代表技术方案一定可行" in r["notice"]
    assert r["boundary_notice"] == BOUNDARY_NOTICE


def test_check_partial_clarification_items_pending_subset():
    data = {"target_system": "SAP", "integration_method": "REST", "sync_mode": "定时"}
    r = check_requirement(T, data)
    assert r["status"] == STATUS_INCOMPLETE
    assert [i["field"] for i in r["pending_items"]] == ["system_version", "auth_method"]
    assert len(r["clarification_items"]) == 5
    assert all(i["status"] == CLARIFICATION_CONFIRMED
               for i in r["clarification_items"] if i["field"] not in ("system_version", "auth_method"))
    assert r["pending_count"] == 2


def test_clarification_items_deterministic():
    assert build_clarification_items(T, FULL) == build_clarification_items(T, FULL)


# ---------------- 摘要 ----------------

def test_summary_ready_has_pending_count_zero():
    s = build_confirmation_summary(T, FULL, "希望对接 ERP", "ERP 系统对接", "某某集团", STATUS_READY)
    assert s["client"] == "某某集团"
    assert s["requirement_name"] == "ERP 系统对接"
    assert s["original_request"] == "希望对接 ERP"
    assert s["status"] == STATUS_READY
    assert s["pending_count"] == 0
    assert len(s["confirmed_info"]) == 5
    assert "不代表技术方案一定可行" in s["boundary_notice"]


def test_summary_incomplete_lists_pending():
    s = build_confirmation_summary(T, {"target_system": "SAP"}, "", "D", "C", STATUS_INCOMPLETE)
    assert s["pending_count"] == 4
    assert all(i["status"] == CLARIFICATION_PENDING for i in s["pending_items"])


def test_summary_confirmed():
    s = build_confirmation_summary(T, FULL, "x", "D", "C", STATUS_CONFIRMED)
    assert s["status_label"] == "已确认"
    assert s["pending_count"] == 0


def test_summary_rejects_invalid_status():
    with pytest.raises(UnknownRequirementStatus):
        build_confirmation_summary(T, FULL, "x", "D", "C", "feasible")


def test_summary_deterministic():
    a = build_confirmation_summary(T, FULL, "x", "D", "C", STATUS_READY)
    b = build_confirmation_summary(T, FULL, "x", "D", "C", STATUS_READY)
    assert a == b


# ---------------- 信息来源 ----------------

def test_normalize_keeps_value_and_source():
    n = normalize_structured_data(T, {
        "target_system": "SAP", "target_system_source": "customer",
        "system_version": "S/4HANA 2023", "system_version_source": "customer",
        "integration_method": "REST API", "integration_method_source": "internal_document",
        "auth_method": "OAuth2", "auth_method_source": "customer",
        "sync_mode": "定时同步", "sync_mode_source": "sales_inference",
    })
    assert n["target_system"] == "SAP"
    assert n["target_system_source"] == "customer"
    assert n["integration_method_source"] == "internal_document"
    assert n["sync_mode_source"] == "sales_inference"


def test_normalize_clears_source_when_value_empty():
    n = normalize_structured_data(T, {"target_system": "", "target_system_source": "customer"})
    assert n["target_system"] == ""
    assert n["target_system_source"] == ""


def test_normalize_rejects_invalid_source():
    with pytest.raises(InvalidSourceError):
        normalize_structured_data(T, {"target_system": "SAP", "target_system_source": "unknown"})


def test_normalize_keeps_value_without_source():
    n = normalize_structured_data(T, {"system_version": "S/4HANA 2024"})
    assert n["system_version"] == "S/4HANA 2024"
    assert n["system_version_source"] == ""


def test_normalize_drops_unknown_keys():
    n = normalize_structured_data(T, {"target_system": "SAP", "junk": "x"})
    assert "junk" not in n


def test_field_entries_no_fake_source():
    entries = get_field_entries(T, {"target_system": "SAP"})
    by = {e["key"]: e for e in entries}
    assert by["target_system"]["source"] is None
    assert by["target_system"]["source_label"] is None
    # 旧数据（无 _source 键）同样不伪造
    legacy = get_field_entries(T, {"system_version": "S/4HANA 2023"})
    assert next(e for e in legacy if e["key"] == "system_version")["source"] is None


def test_field_entries_valid_source_mapped():
    entries = get_field_entries(T, {"sync_mode": "cron", "sync_mode_source": "sales_inference"})
    e = next(x for x in entries if x["key"] == "sync_mode")
    assert e["source"] == "sales_inference"
    assert e["source_label"] == "售前整理"


def test_source_does_not_change_completeness_rule():
    """核心要求：来源缺失不得影响 incomplete / ready 判定。"""
    no_src = check_requirement(T, FULL)
    assert no_src["status"] == STATUS_READY
    assert no_src["missing_fields"] == []
    assert no_src["source_summary"]["without_source"] == 5
    assert no_src["source_missing_labels"] == [
        "目标系统名称", "系统版本", "接口方式", "认证方式", "数据同步方式",
    ]

    with_src = check_requirement(T, {**FULL, "system_version_source": "customer"})
    assert with_src["status"] == STATUS_READY
    assert with_src["missing_fields"] == []

    partial_src = check_requirement(T, {"target_system": "SAP", "target_system_source": "customer"})
    assert partial_src["status"] == STATUS_INCOMPLETE


def test_source_summary_counts():
    s = summarize_sources(T, {
        "target_system": "SAP", "target_system_source": "customer",
        "system_version": "2023", "system_version_source": "customer",
        "auth_method": "OAuth2", "auth_method_source": "customer",
        "integration_method": "REST", "integration_method_source": "internal_document",
        "sync_mode": "cron", "sync_mode_source": "sales_inference",
    })
    assert s["total_filled"] == 5
    assert s["with_source"] == 5
    assert s["without_source"] == 0
    counts = {c["source"]: c["count"] for c in s["counts"]}
    assert counts == {"customer": 3, "internal_document": 1, "sales_inference": 1}
    assert "不代表技术方案已经验证" in s["notice"]


def test_summary_includes_source_per_field():
    s = build_confirmation_summary(
        T,
        {**FULL, "system_version_source": "customer", "sync_mode_source": "sales_inference"},
        "raw", "D", "C", STATUS_CONFIRMED,
    )
    by = {i["label"]: i for i in s["confirmed_info"]}
    assert by["系统版本"]["value"] == "S/4HANA 2023"
    assert by["系统版本"]["source"] == "customer"
    assert by["系统版本"]["source_label"] == "客户确认"
    assert by["数据同步方式"]["source_label"] == "售前整理"
    # 无来源的字段不伪造
    assert by["接口方式"]["source"] is None
    assert "不代表技术方案已经验证" in s["source_notice"]


def test_all_fields_missing():
    r = check_requirement(T, {}, "希望和现有 ERP 对接。")
    assert r["status"] == STATUS_INCOMPLETE
    assert len(r["missing_fields"]) == 5
    assert [f["key"] for f in r["missing_fields"]] == [
        "target_system", "system_version", "integration_method",
        "auth_method", "sync_mode",
    ]
    assert r["status_label"] == "信息不足"
    assert "无法进入方案评估" in r["summary"]


def test_all_fields_empty_string_treated_as_missing():
    r = check_requirement(T, {
        "target_system": "   ", "system_version": "", "integration_method": "",
        "auth_method": "", "sync_mode": "",
    })
    assert r["status"] == STATUS_INCOMPLETE
    assert len(r["missing_fields"]) == 5


def test_partial_missing():
    r = check_requirement(T, {
        "target_system": "SAP",
        "system_version": "",
        "integration_method": "REST",
        "auth_method": "",
        "sync_mode": "定时",
    })
    assert r["status"] == STATUS_INCOMPLETE
    assert [f["label"] for f in r["missing_fields"]] == ["系统版本", "认证方式"]
    assert r["clarification_questions"] == [
        "客户当前使用的系统具体版本是什么？",
        "目标系统接口使用什么认证方式（如 API Key / OAuth2 / 账号密码 / 证书）？",
    ]
    assert "1. " in r["clarification_text"] and "2. " in r["clarification_text"]


def test_all_fields_complete():
    r = check_requirement(T, {
        "target_system": "SAP",
        "system_version": "S/4HANA 2023",
        "integration_method": "REST",
        "auth_method": "OAuth2",
        "sync_mode": "定时",
    })
    assert r["status"] == STATUS_READY
    assert r["missing_fields"] == []
    assert r["clarification_questions"] == []
    assert "可进入方案评估" in r["summary"]
    assert "不代表技术方案一定可行" in r["notice"]


def test_missing_fields_generate_matching_questions():
    data = {
        "target_system": "SAP",
        "system_version": "S/4HANA 2023",
        "integration_method": "REST",
        "auth_method": "OAuth2",
        "sync_mode": "",
    }
    r = check_requirement(T, data)
    assert len(r["clarification_questions"]) == 1
    assert r["missing_fields"][0]["key"] == "sync_mode"
    assert r["clarification_questions"][0] == r["missing_fields"][0]["question"]


def test_none_data_is_safe():
    r = check_requirement(T, None, None)
    assert r["status"] == STATUS_INCOMPLETE
    assert r["has_original_request"] is False


def test_deterministic_same_input_same_output():
    data = {"target_system": "Oracle", "sync_mode": "实时"}
    a = check_requirement(T, data, "对接")
    b = check_requirement(T, data, "对接")
    assert a == b
    # 不包含时间戳等易变字段
    assert set(a.keys()) == set(b.keys())


def test_extra_unknown_keys_ignored():
    r = check_requirement(T, {
        "target_system": "SAP", "system_version": "2023",
        "integration_method": "REST", "auth_method": "OAuth2",
        "sync_mode": "实时", "some_other_field": "x",
    })
    assert r["status"] == STATUS_READY


def test_invalid_requirement_type_raises():
    with pytest.raises(UnknownRequirementType):
        check_requirement("poc_automation", {})