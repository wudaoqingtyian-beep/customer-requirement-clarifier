"""Customer Requirement Clarifier - FastAPI 后端。

边界：只做需求信息录入 / 完整性检查 / 澄清问题生成。
不调用 AI，不判断方案可行性。
"""
from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .requirements import (
    DEFAULT_TYPE,
    STATUS_CONFIRMED,
    STATUS_INCOMPLETE,
    STATUS_READY,
    SOURCES,
    InvalidSourceError,
    UnknownRequirementStatus,
    UnknownRequirementType,
    build_confirmation_summary,
    check_requirement,
    get_fields,
    list_requirement_types,
    normalize_structured_data,
    source_key,
)

STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Customer Requirement Clarifier", version="1.0.0", lifespan=lifespan)


# --------------------------- schemas ---------------------------

class ProjectIn(BaseModel):
    name: str = Field(min_length=1)
    client_name: str = ""
    description: str = ""


class RequirementIn(BaseModel):
    name: str = Field(min_length=1)
    type: str = DEFAULT_TYPE
    original_request: str = ""
    structured_data: dict[str, str] = Field(default_factory=dict)


class RequirementPatch(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    original_request: Optional[str] = None
    structured_data: Optional[dict[str, str]] = None
    # status 不允许直接写入：只能由 /check（incomplete|ready）与 /confirm（confirmed）产生
    status: Optional[str] = None


def _values_changed(
    requirement_type: str,
    old_data: dict[str, Any] | None,
    new_data: dict[str, Any] | None,
) -> bool:
    """仅比较字段「值」，忽略来源变化。"""
    old = old_data or {}
    new = new_data or {}
    return any(
        str(old.get(f["key"]) or "").strip() != str(new.get(f["key"]) or "").strip()
        for f in get_fields(requirement_type)
    )


def _apply_structured_update(
    requirement_type: str,
    old_data: dict[str, Any] | None,
    new_data: dict[str, Any],
) -> dict[str, str]:
    """合并新旧结构化数据，并让「改值即失效旧来源」。

    规则：
    - 新值与旧值不同  -> 该字段旧来源失效（清空），要求重新选择来源
    - 新值与旧值相同  -> 沿用原来源（纯来源调整不影响完整性）
    - 新值被清空      -> 来源强制清空
    """
    old = normalize_structured_data(requirement_type, old_data)
    merged: dict[str, str] = {}
    for f in get_fields(requirement_type):
        key = f["key"]
        skey = source_key(key)
        old_value = old.get(key, "")
        if key in new_data:
            new_value = str(new_data.get(key) or "").strip()
        else:
            new_value = old_value

        # 先按传入来源 + 旧来源填充，再做校验
        candidate = dict(new_data)
        if skey not in candidate:
            candidate[skey] = old.get(skey, "")
        candidate[key] = new_value

        # 值发生变化 -> 旧来源失效
        if new_value != old_value and str(candidate.get(skey) or "").strip() == old.get(skey, ""):
            candidate[skey] = ""

        normalized = _normalize(requirement_type, candidate)
        merged[key] = normalized[key]
        merged[skey] = normalized[skey]
    return merged


def _normalize(requirement_type: str, data: dict[str, Any] | None) -> dict[str, str]:
    """规范化结构化数据（值 + 来源），非法来源返回 400。"""
    try:
        return normalize_structured_data(requirement_type, data)
    except InvalidSourceError as e:
        raise HTTPException(status_code=400, detail=str(e))


# --------------------------- helpers ---------------------------

def _serialize_requirement(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "name": row["name"],
        "type": row["type"],
        "original_request": row["original_request"],
        "structured_data": db.loads(row["structured_data"], {}),
        "status": row["status"],
        "confirmed_at": row["confirmed_at"] if "confirmed_at" in row.keys() else None,
        "check_result": db.loads(row["check_result"], None),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _run_check(req: dict[str, Any]) -> dict[str, Any]:
    try:
        return check_requirement(
            req["type"], req["structured_data"], req["original_request"]
        )
    except UnknownRequirementType:
        raise HTTPException(status_code=400, detail=f"非法需求类型: {req['type']}")


def _build_summary(pid: int, req: dict[str, Any]) -> dict[str, Any]:
    with db.get_connection() as conn:
        prow = conn.execute(
            "SELECT client_name FROM projects WHERE id = ?", (pid,)
        ).fetchone()
    client_name = prow["client_name"] if prow else ""
    try:
        return build_confirmation_summary(
            req["type"], req["structured_data"], req["original_request"],
            req["name"], client_name, req["status"],
        )
    except UnknownRequirementStatus:
        raise HTTPException(status_code=400, detail=f"非法需求状态: {req['status']}")


def _get_project_or_404(pid: int) -> dict[str, Any]:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    return dict(row)


def _get_requirement_or_404(rid: int) -> dict[str, Any]:
    with db.get_connection() as conn:
        row = conn.execute("SELECT * FROM requirements WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="需求不存在")
    return _serialize_requirement(row)


def _validate_type(t: str) -> None:
    try:
        check_requirement(t, {})
    except UnknownRequirementType:
        raise HTTPException(status_code=400, detail=f"非法需求类型: {t}")


def _persist_check(conn: sqlite3.Connection, rid: int, result: dict[str, Any]) -> None:
    """保存检查结果。

    重要：检查只会产出 incomplete / ready。
    若需求原本已 confirmed，重新检查会按最新字段完整性回退状态，
    避免「显示 confirmed 但字段已缺失」的错误结论。
    """
    conn.execute(
        "UPDATE requirements SET status = ?, check_result = ?, confirmed_at = NULL,"
        " updated_at = ? WHERE id = ?",
        (result["status"], db.dumps(result), db.utcnow(), rid),
    )


# --------------------------- meta ---------------------------

@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/requirement-types")
def requirement_types() -> list[dict[str, Any]]:
    return [
        {**t, "sources": [{"value": k, "label": v} for k, v in SOURCES.items()]}
        for t in list_requirement_types()
    ]


@app.get("/api/sources")
def sources() -> list[dict[str, str]]:
    return [{"value": k, "label": v} for k, v in SOURCES.items()]


# --------------------------- projects ---------------------------

@app.get("/api/projects")
def list_projects() -> list[dict[str, Any]]:
    with db.get_connection() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
        counts = conn.execute(
            "SELECT project_id, COUNT(*) AS c FROM requirements GROUP BY project_id"
        ).fetchall()
    cmap = {r["project_id"]: r["c"] for r in counts}
    result = []
    for r in rows:
        d = dict(r)
        d["requirement_count"] = cmap.get(d["id"], 0)
        result.append(d)
    return result


@app.post("/api/projects", status_code=201)
def create_project(payload: ProjectIn) -> dict[str, Any]:
    now = db.utcnow()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, client_name, description, status, created_at)"
            " VALUES (?, ?, ?, 'active', ?)",
            (payload.name, payload.client_name, payload.description, now),
        )
        pid = cur.lastrowid
    return _get_project_or_404(pid)


@app.get("/api/projects/{pid}")
def get_project(pid: int) -> dict[str, Any]:
    project = _get_project_or_404(pid)
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM requirements WHERE project_id = ? ORDER BY id", (pid,)
        ).fetchall()
    project["requirements"] = [_serialize_requirement(r) for r in rows]
    return project


@app.delete("/api/projects/{pid}")
def delete_project(pid: int) -> dict[str, str]:
    _get_project_or_404(pid)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM requirements WHERE project_id = ?", (pid,))
        conn.execute("DELETE FROM projects WHERE id = ?", (pid,))
    return {"status": "deleted"}


# --------------------------- requirements ---------------------------

@app.post("/api/projects/{pid}/requirements", status_code=201)
def create_requirement(pid: int, payload: RequirementIn) -> dict[str, Any]:
    _get_project_or_404(pid)
    _validate_type(payload.type)
    data = _normalize(payload.type, payload.structured_data)
    now = db.utcnow()
    with db.get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO requirements"
            " (project_id, name, type, original_request, structured_data, status, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                pid,
                payload.name,
                payload.type,
                payload.original_request,
                db.dumps(data),
                STATUS_INCOMPLETE,
                now,
                now,
            ),
        )
        rid = cur.lastrowid
    return _get_requirement_or_404(rid)


@app.get("/api/projects/{pid}/requirements")
def list_requirements(pid: int) -> list[dict[str, Any]]:
    _get_project_or_404(pid)
    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM requirements WHERE project_id = ? ORDER BY id", (pid,)
        ).fetchall()
    return [_serialize_requirement(r) for r in rows]


@app.get("/api/requirements/{rid}")
def get_requirement(rid: int) -> dict[str, Any]:
    return _get_requirement_or_404(rid)


@app.patch("/api/requirements/{rid}")
def patch_requirement(rid: int, payload: RequirementPatch) -> dict[str, Any]:
    current = _get_requirement_or_404(rid)
    if payload.status is not None:
        raise HTTPException(
            status_code=400,
            detail="状态不可直接修改，请通过检查(/check)或确认(/confirm)接口",
        )
    if payload.type is not None:
        _validate_type(payload.type)
        current["type"] = payload.type
    if payload.name is not None:
        if not payload.name.strip():
            raise HTTPException(status_code=400, detail="需求名称不能为空")
        current["name"] = payload.name
    if payload.original_request is not None:
        current["original_request"] = payload.original_request
    if payload.structured_data is not None:
        previous_data = dict(current["structured_data"])
        current["structured_data"] = _apply_structured_update(
            current["type"], previous_data, payload.structured_data
        )
    else:
        previous_data = dict(current["structured_data"])

    with db.get_connection() as conn:
        conn.execute(
            "UPDATE requirements SET name = ?, type = ?, original_request = ?,"
            " structured_data = ?, updated_at = ? WHERE id = ?",
            (
                current["name"],
                current["type"],
                current["original_request"],
                db.dumps(current["structured_data"]),
                db.utcnow(),
                rid,
            ),
        )
        # 已确认需求被编辑核心字段值后，立即按最新完整性回退，
        # 避免旧 confirmed 伪装成当前结论。
        # 仅调整来源（值未变）不触发回退，来源不参与完整性判断。
        if current["status"] == STATUS_CONFIRMED and _values_changed(
            current["type"], previous_data, current["structured_data"]
        ):
            _persist_check(conn, rid, _run_check(current))
    return _get_requirement_or_404(rid)


@app.delete("/api/requirements/{rid}")
def delete_requirement(rid: int) -> dict[str, str]:
    _get_requirement_or_404(rid)
    with db.get_connection() as conn:
        conn.execute("DELETE FROM requirements WHERE id = ?", (rid,))
    return {"status": "deleted"}


@app.post("/api/requirements/{rid}/check")
def check(rid: int) -> dict[str, Any]:
    req = _get_requirement_or_404(rid)
    result = _run_check(req)
    with db.get_connection() as conn:
        _persist_check(conn, rid, result)
    return _get_requirement_or_404(rid)


@app.post("/api/requirements/{rid}/confirm")
def confirm(rid: int) -> dict[str, Any]:
    """售前人工确认需求。仅当当前字段完整性达到 ready 时允许确认。

    该接口不会做任何技术可行性判断。
    """
    req = _get_requirement_or_404(rid)
    result = _run_check(req)
    if result["status"] != STATUS_READY:
        raise HTTPException(
            status_code=400,
            detail="信息不足，无法确认需求，请先补全必填技术信息",
        )
    now = db.utcnow()
    with db.get_connection() as conn:
        conn.execute(
            "UPDATE requirements SET status = ?, check_result = ?, confirmed_at = ?,"
            " updated_at = ? WHERE id = ?",
            (STATUS_CONFIRMED, db.dumps(result), now, now, rid),
        )
    return _get_requirement_or_404(rid)


@app.get("/api/requirements/{rid}/summary")
def summary(rid: int) -> dict[str, Any]:
    """需求确认摘要（确定性生成，无时间/随机依赖）。"""
    req = _get_requirement_or_404(rid)
    return _build_summary(req["project_id"], req)


# --------------------------- static ---------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")