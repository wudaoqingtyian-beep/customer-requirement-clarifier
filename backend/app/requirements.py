"""需求类型定义 + 确定性信息完整性检查逻辑。

设计约束：
- 纯函数，不依赖数据库、前端、时间、随机数。
- 相同输入 -> 相同输出。
- 不调用任何 LLM / 外部 API。
"""
from __future__ import annotations

from typing import Any

STATUS_INCOMPLETE = "incomplete"
STATUS_READY = "ready"
STATUS_CONFIRMED = "confirmed"

ALL_STATUSES = (STATUS_INCOMPLETE, STATUS_READY, STATUS_CONFIRMED)

# 需求状态含义（仅供 UI 文案与文档引用，系统不做技术可行性判断）
STATUS_LABELS = {
    STATUS_INCOMPLETE: "信息不足",
    STATUS_READY: "可进入方案评估",
    STATUS_CONFIRMED: "已确认",
}

CLARIFICATION_PENDING = "pending"
CLARIFICATION_CONFIRMED = "confirmed"

BOUNDARY_NOTICE = (
    "可进入方案评估不代表技术方案一定可行。"
    "「已确认」仅表示当前客户需求信息已整理并由售前确认，不代表技术方案一定可行。"
)

SOURCE_SUFFIX = "_source"

# 信息来源：仅三种固定枚举，不接受自由文本
SOURCES: dict[str, str] = {
    "customer": "客户确认",
    "internal_document": "内部资料",
    "sales_inference": "售前整理",
}

SOURCE_NOTICE = "来源仅用于记录信息依据，不代表技术方案已经验证。"


class InvalidSourceError(ValueError):
    """写入了不允许的信息来源。"""

TYPE_SYSTEM_INTEGRATION = "system_integration"

# 每种需求类型的结构化字段定义（顺序即 UI / 报告顺序）
TYPE_FIELDS: dict[str, list[dict[str, str]]] = {
    TYPE_SYSTEM_INTEGRATION: [
        {
            "key": "target_system",
            "label": "目标系统名称",
            "question": "需要对接的目标系统（产品名称）是什么？",
        },
        {
            "key": "system_version",
            "label": "系统版本",
            "question": "客户当前使用的系统具体版本是什么？",
        },
        {
            "key": "integration_method",
            "label": "接口方式",
            "question": "目标系统对外提供哪些接口方式（如 REST / SOAP / 数据库直连 / 文件交换）？",
        },
        {
            "key": "auth_method",
            "label": "认证方式",
            "question": "目标系统接口使用什么认证方式（如 API Key / OAuth2 / 账号密码 / 证书）？",
        },
        {
            "key": "sync_mode",
            "label": "数据同步方式",
            "question": "数据同步方式是什么（实时接口调用 / 定时任务 / 消息队列 / 批量文件）？",
        },
    ],
}

TYPE_LABELS: dict[str, str] = {
    TYPE_SYSTEM_INTEGRATION: "系统集成",
}

DEFAULT_TYPE = TYPE_SYSTEM_INTEGRATION


class UnknownRequirementType(ValueError):
    """传入未定义的需求类型。"""


class UnknownRequirementStatus(ValueError):
    """传入非法需求状态值。"""


def list_requirement_types() -> list[dict[str, Any]]:
    return [
        {
            "type": t,
            "label": TYPE_LABELS[t],
            "fields": TYPE_FIELDS[t],
        }
        for t in TYPE_FIELDS
    ]


def get_fields(requirement_type: str) -> list[dict[str, str]]:
    if requirement_type not in TYPE_FIELDS:
        raise UnknownRequirementType(requirement_type)
    return TYPE_FIELDS[requirement_type]


def _is_empty(value: Any) -> bool:
    return value is None or not str(value).strip()


def source_key(field_key: str) -> str:
    return f"{field_key}{SOURCE_SUFFIX}"


def normalize_structured_data(
    requirement_type: str,
    structured_data: dict[str, Any] | None,
) -> dict[str, str]:
    """规范化结构化数据，保证「值 + 来源」始终一致。

    规则（纯函数）：
    - 字段值为空        -> 来源强制清空（不存在「空值但有来源」的脏数据）
    - 来源不在枚举内    -> 抛 InvalidSourceError
    - 未知字段 / 未知键 -> 丢弃（只保留本类型定义的字段及其 _source）
    """
    data = structured_data or {}
    out: dict[str, str] = {}
    for f in get_fields(requirement_type):
        key = f["key"]
        raw = data.get(key)
        value = "" if raw is None else str(raw).strip()
        out[key] = value

        skey = source_key(key)
        sraw = data.get(skey)
        sval = "" if sraw is None else str(sraw).strip()

        if not value:
            # 值清空 -> 来源必须清空
            out[skey] = ""
            continue
        if not sval:
            out[skey] = ""
            continue
        if sval not in SOURCES:
            raise InvalidSourceError(f"非法信息来源: {sval}")
        out[skey] = sval
    return out


def get_field_entries(
    requirement_type: str,
    structured_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """返回每个字段的 {key,label,value,source,source_label}，供 UI / 摘要使用。

    只做读取，不做判断；缺失来源返回 None，不伪造默认值。
    """
    data = structured_data or {}
    entries: list[dict[str, Any]] = []
    for f in get_fields(requirement_type):
        raw = data.get(f["key"])
        value = "" if raw is None else str(raw).strip()
        sraw = data.get(source_key(f["key"]))
        source = sraw if sraw in SOURCES else None
        entries.append(
            {
                "key": f["key"],
                "label": f["label"],
                "value": value,
                "source": source,
                "source_label": SOURCES.get(source) if source else None,
            }
        )
    return entries


def summarize_sources(
    requirement_type: str,
    structured_data: dict[str, Any] | None,
) -> dict[str, Any]:
    """来源概览：按三种枚举统计已填写字段的来源分布。"""
    entries = get_field_entries(requirement_type, structured_data)
    filled = [e for e in entries if e["value"]]
    counts = {k: 0 for k in SOURCES}
    for e in filled:
        if e["source"]:
            counts[e["source"]] += 1
    return {
        "total_filled": len(filled),
        "with_source": sum(counts.values()),
        "without_source": len(filled) - sum(counts.values()),
        "counts": [
            {"source": k, "label": SOURCES[k], "count": counts[k]}
            for k in SOURCES
        ],
        "notice": SOURCE_NOTICE,
    }


def build_clarification_items(
    requirement_type: str,
    structured_data: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """为每个必填字段生成澄清项。

    单一数据源原则：结构化字段是唯一事实来源。
    - 字段有值  -> status=confirmed, answer=字段值
    - 字段为空  -> status=pending,   answer=""
    因此不会出现「字段已填但澄清项仍 pending」的不一致。
    """
    data = structured_data or {}
    items: list[dict[str, Any]] = []
    for f in get_fields(requirement_type):
        raw = data.get(f["key"])
        filled = not _is_empty(raw)
        items.append(
            {
                "field": f["key"],
                "label": f["label"],
                "question": f["question"],
                "status": CLARIFICATION_CONFIRMED if filled else CLARIFICATION_PENDING,
                "answer": "" if raw is None else str(raw).strip(),
            }
        )
    return items


def check_requirement(
    requirement_type: str,
    structured_data: dict[str, Any] | None,
    original_request: str | None = None,
) -> dict[str, Any]:
    """执行信息完整性检查，返回确定性结果。

    注意：本函数只产出 incomplete / ready，永不产出 confirmed。
    confirmed 只能由用户主动调用确认接口产生。

    返回结构：
    {
        "status": "incomplete" | "ready",
        "status_label": "信息不足" | "可进入方案评估",
        "checked_fields": [...],
        "missing_fields": [{"key","label","question"}],
        "clarification_items": [{field,label,question,status,answer}],
        "pending_items": [同上，仅 status=pending],
        "clarification_questions": [str, ...],   # 兼容旧字段：待澄清问题
        "summary": str,
        "notice": str
    }
    """
    fields = get_fields(requirement_type)
    data = structured_data or {}

    checked = [
        {"key": f["key"], "label": f["label"], "value": ("" if data.get(f["key"]) is None else str(data.get(f["key"])))}
        for f in fields
    ]

    missing = [f for f in fields if _is_empty(data.get(f["key"]))]

    items = build_clarification_items(requirement_type, data)
    pending_items = [i for i in items if i["status"] == CLARIFICATION_PENDING]
    sources = summarize_sources(requirement_type, data)

    if missing:
        status = STATUS_INCOMPLETE
        status_label = STATUS_LABELS[STATUS_INCOMPLETE]
        summary = "信息不足，当前无法进入方案评估。"
        questions = [f["question"] for f in missing]
        clarification = "当前无法进入方案评估，需先向客户确认以下信息：\n" + "\n".join(
            f"{i}. {q}" for i, q in enumerate(questions, 1)
        )
    else:
        status = STATUS_READY
        status_label = STATUS_LABELS[STATUS_READY]
        summary = "信息已基本完整，可进入方案评估，等待售前人工确认。"
        questions = []
        clarification = "无待澄清问题。"

    return {
        "status": status,
        "status_label": status_label,
        "requirement_type": requirement_type,
        "requirement_type_label": TYPE_LABELS[requirement_type],
        "checked_fields": checked,
        "missing_fields": [
            {"key": f["key"], "label": f["label"], "question": f["question"]}
            for f in missing
        ],
        "clarification_items": items,
        "pending_items": pending_items,
        "pending_count": len(pending_items),
        "clarification_questions": questions,
        "source_summary": sources,
        "source_missing_labels": [
            f["label"] for f in get_fields(requirement_type)
            if not _is_empty(data.get(f["key"])) and data.get(source_key(f["key"])) not in SOURCES
        ],
        "summary": summary,
        "clarification_text": clarification,
        "has_original_request": not _is_empty(original_request),
        "notice": (
            "本结论仅表示信息已满足当前澄清规则，可进入下一阶段评估，"
            "不代表技术方案一定可行。"
        ),
        "boundary_notice": BOUNDARY_NOTICE,
    }


def build_confirmation_summary(
    requirement_type: str,
    structured_data: dict[str, Any] | None,
    original_request: str | None,
    requirement_name: str,
    client_name: str,
    status: str,
) -> dict[str, Any]:
    """生成结构化的「需求确认摘要」（纯函数，无时间/随机依赖）。"""
    if status not in ALL_STATUSES:
        raise UnknownRequirementStatus(status)
    data = structured_data or {}
    items = build_clarification_items(requirement_type, data)
    pending = [i for i in items if i["status"] == CLARIFICATION_PENDING]
    entries = get_field_entries(requirement_type, data)

    return {
        "client": client_name,
        "requirement_name": requirement_name,
        "original_request": original_request or "",
        "confirmed_info": [
            {
                "label": e["label"],
                "value": e["value"],
                "source": e["source"],
                "source_label": e["source_label"],
            }
            for e in entries
        ],
        "source_summary": summarize_sources(requirement_type, data),
        "status": status,
        "status_label": STATUS_LABELS[status],
        "pending_items": pending,
        "pending_count": len(pending),
        "boundary_notice": BOUNDARY_NOTICE,
        "source_notice": SOURCE_NOTICE,
    }