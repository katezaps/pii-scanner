"""POST /audit — streaming SSE audit endpoint."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from psycopg import AsyncConnection
from sse_starlette.sse import EventSourceResponse

from src.core.auth import AuthDep
from src.core.config import WebSettings, get_settings
from src.core.names import generate_name
from src.db.pool import acquire
from src.db.queries import sql
from src.models.audit import (
    AuditAgentResultOut,
    FormFieldMatchOut,
    RunAuditAgentsRequest,
)
from src.models.enums import ScanState
from src.models.scan import AuditAgentResult
from src.services.audit.orchestrator import resolve_brokers, stream_audit_agents

logger = logging.getLogger(__name__)

VALID_FIELD_TYPES = {"email", "phone", "name", "address"}

router = APIRouter(tags=["audit"])


def _status_field_name(broker_name: str, execution_id) -> str:
    """Consistent field_name for _status marker rows."""
    return f"agent:{broker_name}:_status:{execution_id}"


def _field_scan_name(broker_name: str, identity_field: str) -> str:
    """Consistent field_name for identity field scan rows."""
    return f"agent:{broker_name}:{identity_field}"


async def _persist_agent_result(
    conn: AsyncConnection,
    execution_id,
    result: AuditAgentResult,
    expires_at: datetime,
    settings: WebSettings,
    user_id,
) -> None:
    """Persist all results from a single agent into broker_field_scans.

    Stores every matched input regardless of found status — found=True
    (PII detected), found=False (checked but not found), and found=None
    (form input discovered but not checked). Also stores each
    input_fields_found entry that wasn't already covered by a match,
    with found=None to record that the broker accepts that field type.

    When the agent errors (cancelled / timed out / failed), a single
    CANCELLED or FAILED row is persisted so the broker appears in
    result history with its terminal state.
    """

    async with conn.cursor() as cur:
        await cur.execute(sql("audit_get_broker_by_name"), (result.name,))
        broker_row = await cur.fetchone()
        if broker_row is None:
            return

        broker_id = broker_row["id"]

        # Cancelled or failed — persist a marker row (and any partial detections).
        # "Completed at timeout." is treated as success — results are stored normally.
        if result.message and result.message != "Completed at timeout.":
            state = ScanState.CANCELLED if result.message == "Cancelled." else ScanState.FAILED

            # Persist any partial PII detections collected before cancellation
            for m in result.matched_inputs:
                field_name = _field_scan_name(result.name, m.identity_field)

                await cur.execute(
                    sql("audit_upsert_field_scan"),
                    (
                        uuid4(),
                        field_name,
                        m.identity_field,
                        broker_id,
                        state,
                        bool(m.found),
                        result.message,
                        expires_at,
                        user_id,
                    ),
                )
                bfs_row = await cur.fetchone()

                await cur.execute(
                    sql("audit_upsert_result"),
                    (execution_id, bfs_row["id"], "FRESH"),
                )

            # Persist the _status marker
            status_field_name = _status_field_name(result.name, execution_id)
            await cur.execute(
                sql("audit_upsert_field_scan"),
                (
                    uuid4(),
                    status_field_name,
                    "_status",
                    broker_id,
                    state,
                    False,
                    result.message,
                    expires_at,
                    user_id,
                ),
            )
            bfs_row = await cur.fetchone()

            await cur.execute(
                sql("audit_upsert_result"),
                (execution_id, bfs_row["id"], "FRESH"),
            )
            return

        stored_fields: set[str] = set()
        persist_message = result.message  # e.g. "Completed at timeout." or None

        # Store all matched inputs
        for m in result.matched_inputs:
            field_name = _field_scan_name(result.name, m.identity_field)
            stored_fields.add(m.identity_field)

            await cur.execute(
                sql("audit_upsert_field_scan"),
                (
                    uuid4(),
                    field_name,
                    m.identity_field,
                    broker_id,
                    ScanState.SUCCESS,
                    bool(m.found),
                    persist_message,
                    expires_at,
                    user_id,
                ),
            )
            bfs_row = await cur.fetchone()

            await cur.execute(
                sql("audit_upsert_result"),
                (execution_id, bfs_row["id"], "FRESH"),
            )

        # Store discovered input fields not already covered by a match.
        # Only persist known identity field types.
        for field_type in result.input_fields_found:
            if field_type in stored_fields:
                continue
            if field_type not in VALID_FIELD_TYPES:
                continue

            field_name = _field_scan_name(result.name, field_type)

            await cur.execute(
                sql("audit_upsert_field_scan"),
                (
                    uuid4(),
                    field_name,
                    field_type,
                    broker_id,
                    ScanState.SUCCESS,
                    False,
                    None,
                    expires_at,
                    user_id,
                ),
            )
            bfs_row = await cur.fetchone()

            await cur.execute(
                sql("audit_upsert_result"),
                (execution_id, bfs_row["id"], "FRESH"),
            )

        # Mark the _status marker as SUCCESS now that the broker completed
        status_hash = _status_field_name(result.name, execution_id)
        await cur.execute(
            sql("audit_upsert_field_scan"),
            (
                uuid4(),
                status_hash,
                "_status",
                broker_id,
                ScanState.SUCCESS,
                False,
                None,
                expires_at,
                user_id,
            ),
        )


@router.post(
    "/audit",
    summary="Stream audit agent results as SSE events",
    response_class=EventSourceResponse,
)
async def run_agents(
    payload: RunAuditAgentsRequest,
    auth: AuthDep,
    settings: Annotated[WebSettings, Depends(get_settings)],
) -> EventSourceResponse:
    """Stream audit results as each broker agent completes.

    Results with PII detection (found=true/false) are persisted to
    broker_field_scans so they're available via GET /fetch.

    Events:
      - started: list of brokers being scanned + accepted fields
      - result: one per broker as its agent finishes
      - done: all agents finished
    """
    accepted = []
    identity: dict[str, str] = {}
    for field_type in ("email", "phone", "name", "address"):
        value = getattr(payload, field_type)
        if value is not None and value.strip():
            accepted.append({"field_type": field_type, "status": field_type})
            identity[field_type] = value.strip()

    brokers = await resolve_brokers(payload.broker_keys)
    broker_list = [{"name": b["name"], "search_url": b["search_url"]} for b in brokers]

    save = payload.save
    scan_name = payload.scan_name

    # If user provided a name, check for collision before streaming
    if save and scan_name:
        async with acquire() as conn:
            async with conn.cursor() as cur:
                await cur.execute(sql("audit_check_name"), (auth.user_id, scan_name))
                if await cur.fetchone():
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"A scan named '{scan_name}' already exists",
                    )

    async def event_stream():
        execution_id = None
        resolved_name = scan_name if save else None
        expires_at = datetime.now(UTC) + timedelta(
            days=settings.scan_retention_days,
        )

        async with acquire() as conn:
            # Cancel any in-flight scans for this user
            async with conn.cursor() as cur:
                await cur.execute(sql("audit_cancel_running"), (auth.user_id,))
                await cur.execute(sql("audit_cancel_running_executions"), (auth.user_id,))
                await conn.commit()

            if save:
                async with conn.cursor() as cur:
                    await cur.execute(sql("health_broker_version"))
                    row = await cur.fetchone()
                    current_version = int(row["v"])

                    # Generate a name if not provided, retrying on collision
                    if not resolved_name:
                        for _ in range(10):
                            candidate = generate_name()
                            await cur.execute(
                                sql("audit_check_name"),
                                (auth.user_id, candidate),
                            )
                            if not await cur.fetchone():
                                resolved_name = candidate
                                break
                        else:
                            resolved_name = f"{generate_name()}_{uuid4().hex[:6]}"
                    execution_id = uuid4()
                    await cur.execute(
                        sql("audit_insert_execution"),
                        (
                            execution_id,
                            auth.user_id,
                                current_version,
                            expires_at,
                            resolved_name,
                        ),
                    )
                    result_row = await cur.fetchone()
                    execution_id = result_row["id"]

                    # Pre-create RUNNING _status markers for every broker
                    # so audit_cancel_running can flip them to CANCELLED.
                    for broker in broker_list:
                        await cur.execute(
                            sql("audit_get_broker_by_name"),
                            (broker["name"],),
                        )
                        b_row = await cur.fetchone()
                        if b_row is None:
                            continue
                        bfs_id = uuid4()
                        field_name = _status_field_name(broker["name"], execution_id)
                        await cur.execute(
                            sql("audit_upsert_field_scan"),
                            (
                                bfs_id,
                                field_name,
                                "_status",
                                b_row["id"],
                                        ScanState.RUNNING,
                                False,
                                None,
                                expires_at,
                                auth.user_id,
                            ),
                        )
                        marker_row = await cur.fetchone()
                        await cur.execute(
                            sql("audit_upsert_result"),
                            (execution_id, marker_row["id"], "FRESH"),
                        )

                    await conn.commit()

            yield {
                "event": "started",
                "data": json.dumps(
                    {
                        "accepted": accepted,
                        "brokers": broker_list,
                        "scan_name": resolved_name,
                    }
                ),
            }

            # Track which brokers have been persisted so we can mark
            # the rest as CANCELLED if the client disconnects mid-scan.
            brokers_by_name = {b["name"]: b for b in broker_list}
            persisted_brokers: set[str] = set()

            try:
                async for r in stream_audit_agents(
                    broker_keys=list(payload.broker_keys),
                    identity=identity if identity else None,
                ):
                    if save and execution_id is not None:
                        try:
                            await _persist_agent_result(
                                conn,
                                execution_id,
                                r,
                                expires_at,
                                settings,
                                auth.user_id,
                            )
                            await conn.commit()
                            persisted_brokers.add(r.name)
                        except Exception:
                            logger.exception("Failed to persist result for %s", r.name)
                            await conn.rollback()

                    # Filter input_fields_found to only user's identity fields
                    identity_keys = set(identity.keys()) if identity else set()
                    relevant_fields = (
                        [f for f in r.input_fields_found if f in identity_keys]
                        if identity_keys
                        else r.input_fields_found
                    )

                    out = AuditAgentResultOut(
                        name=r.name,
                        search_url=r.search_url,
                        status_code=r.status_code,
                        content_length=r.content_length,
                        message=r.message,
                        input_fields_found=relevant_fields,
                        matched_inputs=[
                            FormFieldMatchOut(
                                identity_field=m.identity_field,
                                form_input=m.form_input,
                                found=m.found,
                            )
                            for m in r.matched_inputs
                        ],
                    )
                    yield {
                        "event": "result",
                        "data": out.model_dump_json(),
                    }
            except Exception:
                logger.exception("Error in audit agent stream")
                yield {
                    "event": "error",
                    "data": json.dumps({"error": "Audit agent failed"}),
                }
            finally:
                # Persist CANCELLED for any brokers that never got a result
                if save and execution_id is not None:
                    missing = set(brokers_by_name) - persisted_brokers
                    if missing:
                        for name in missing:
                            cancelled = AuditAgentResult(
                                name=name,
                                search_url=brokers_by_name[name]["search_url"],
                                status_code=None,
                                content_length=None,
                                message="Cancelled.",
                            )
                            try:
                                await _persist_agent_result(
                                    conn,
                                    execution_id,
                                    cancelled,
                                    expires_at,
                                    settings,
                                    auth.user_id,
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to persist cancellation for %s",
                                    name,
                                )

                    # Mark execution as SUCCESS or CANCELLED
                    exec_state = ScanState.CANCELLED if missing else ScanState.SUCCESS
                    try:
                        async with conn.cursor() as cur:
                            await cur.execute(
                                sql("audit_complete_execution"),
                                (exec_state, execution_id, auth.user_id),
                            )
                        await conn.commit()
                    except Exception:
                        logger.exception("Failed to update execution state")

        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(event_stream())
