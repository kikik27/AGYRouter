import hashlib
import hmac
import os
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.config import (
    ALLOW_TOOL_EXECUTION,
    API_KEY,
    DASHBOARD_PASSWORD,
    DATA_DIR,
    DEFAULT_MODEL,
    MODEL_ALIASES,
)


def get_db_path() -> Path:
    """Resolve SQLite database path dynamically (supports AGY_DB_PATH override for tests)."""
    override = os.getenv("AGY_DB_PATH", "").strip()
    path = Path(override) if override else (DATA_DIR / "agy_proxy.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    """Yield a short-lived WAL-mode SQLite connection."""
    conn = sqlite3.connect(str(get_db_path()), timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# --- Password & Session Cryptography ---

def hash_password(password: str) -> str:
    """Hash a password using PBKDF2-HMAC-SHA256 with a random 16-byte salt."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2 hash."""
    if not stored or "$" not in stored:
        return False
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(hash_hex)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(candidate, expected)
    except Exception:
        return False


def create_session_token(ttl_seconds: int = 30 * 86400) -> str:
    """Create a signed session token: <exp_ts>.<nonce>.<hmac_hex>."""
    secret = get_setting("session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        set_setting("session_secret", secret)
    exp_ts = int(time.time()) + ttl_seconds
    nonce = secrets.token_hex(12)
    payload = f"{exp_ts}.{nonce}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: Optional[str]) -> bool:
    """Validate HMAC signature and expiration of a session token."""
    if not token or token.count(".") != 2:
        return False
    secret = get_setting("session_secret")
    if not secret:
        return False
    try:
        exp_str, nonce, sig_hex = token.split(".", 2)
        exp_ts = int(exp_str)
        if exp_ts < int(time.time()):
            return False
        payload = f"{exp_str}.{nonce}"
        expected_sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig_hex, expected_sig)
    except Exception:
        return False


# --- Schema & Seeding ---

def init_db() -> None:
    """Idempotently initialize SQLite schema and seed defaults."""
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                key_value TEXT UNIQUE NOT NULL,
                key_prefix TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                allowed_model TEXT NOT NULL DEFAULT '*',
                created_at INTEGER NOT NULL,
                last_used_at INTEGER,
                request_count INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS model_routes (
                alias TEXT PRIMARY KEY,
                target_model TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS request_logs (
                id TEXT PRIMARY KEY,
                timestamp INTEGER NOT NULL,
                api_key_id TEXT,
                api_key_name TEXT,
                endpoint TEXT NOT NULL,
                requested_model TEXT,
                resolved_model TEXT,
                stream INTEGER NOT NULL DEFAULT 0,
                status_code INTEGER NOT NULL,
                latency_ms INTEGER NOT NULL DEFAULT 0,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                conversation_id TEXT,
                prompt_preview TEXT,
                error_message TEXT
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts ON request_logs(timestamp DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_logs_key_ts ON request_logs(api_key_id, timestamp DESC)")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_key TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                updated_at INTEGER NOT NULL
            )
            """
        )

        # Seed settings if missing
        def seed_setting(k: str, v: str) -> None:
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))

        row = conn.execute("SELECT value FROM settings WHERE key = 'password_hash'").fetchone()
        if row is None:
            seed_setting("password_hash", hash_password(DASHBOARD_PASSWORD))
            seed_setting("is_default_password", "1")

        seed_setting("session_secret", secrets.token_hex(32))
        seed_setting("require_api_key", "1")
        seed_setting("default_model", DEFAULT_MODEL)
        seed_setting("allow_tool_execution", "1" if ALLOW_TOOL_EXECUTION else "0")
        seed_setting("tunnel_autostart", "0")
        seed_setting("tunnel_mode", "quick")
        seed_setting("tunnel_protocol", "http2")
        seed_setting("tunnel_token", "")
        seed_setting("tunnel_custom_url", "")

        # Seed model_routes from MODEL_ALIASES if empty
        route_count = conn.execute("SELECT COUNT(*) AS cnt FROM model_routes").fetchone()["cnt"]
        if route_count == 0:
            for alias, target in MODEL_ALIASES.items():
                conn.execute(
                    "INSERT OR IGNORE INTO model_routes (alias, target_model, description, updated_at) VALUES (?, ?, ?, ?)",
                    (alias, target, "Built-in framework compatibility alias", now),
                )

        # Seed initial API key if empty
        key_count = conn.execute("SELECT COUNT(*) AS cnt FROM api_keys").fetchone()["cnt"]
        if key_count == 0:
            initial_key = API_KEY if API_KEY else f"sk-agy-{secrets.token_hex(20)}"
            prefix = f"{initial_key[:11]}..." if len(initial_key) > 12 else initial_key
            conn.execute(
                """
                INSERT INTO api_keys (id, name, key_value, key_prefix, is_active, allowed_model, created_at)
                VALUES (?, ?, ?, ?, 1, '*', ?)
                """,
                (f"key_{uuid.uuid4().hex[:10]}", "Default Local Key", initial_key, prefix, now),
            )


# --- Settings Helpers ---

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


# --- API Keys CRUD & Usage ---

def _row_to_key(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "key_value": row["key_value"],
        "key_prefix": row["key_prefix"],
        "is_active": bool(row["is_active"]),
        "allowed_model": row["allowed_model"],
        "created_at": row["created_at"],
        "last_used_at": row["last_used_at"],
        "request_count": row["request_count"],
        "total_tokens": row["total_tokens"],
    }


def list_api_keys() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [_row_to_key(r) for r in rows]


def create_api_key(name: str, allowed_model: str = "*") -> Dict[str, Any]:
    now = int(time.time())
    key_id = f"key_{uuid.uuid4().hex[:10]}"
    key_value = f"sk-agy-{secrets.token_hex(20)}"
    key_prefix = f"{key_value[:11]}..."
    clean_name = (name or "Untitled Key").strip()
    clean_model = (allowed_model or "*").strip() or "*"

    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO api_keys (id, name, key_value, key_prefix, is_active, allowed_model, created_at)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (key_id, clean_name, key_value, key_prefix, clean_model, now),
        )
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_key(row)


def update_api_key(
    key_id: str,
    name: Optional[str] = None,
    is_active: Optional[bool] = None,
    allowed_model: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    updates: List[str] = []
    params: List[Any] = []
    if name is not None:
        updates.append("name = ?")
        params.append(name.strip() or "Untitled Key")
    if is_active is not None:
        updates.append("is_active = ?")
        params.append(1 if is_active else 0)
    if allowed_model is not None:
        updates.append("allowed_model = ?")
        params.append(allowed_model.strip() or "*")

    if not updates:
        with get_conn() as conn:
            row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
            return _row_to_key(row) if row else None

    params.append(key_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE api_keys SET {', '.join(updates)} WHERE id = ?", params)
        row = conn.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
        return _row_to_key(row) if row else None


def delete_api_key(key_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM api_keys WHERE id = ?", (key_id,))
        return cur.rowcount > 0


def validate_api_key(raw_key: str) -> Optional[Dict[str, Any]]:
    if not raw_key:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_value = ? AND is_active = 1",
            (raw_key.strip(),),
        ).fetchone()
        return _row_to_key(row) if row else None


def record_key_usage(key_id: Optional[str], total_tokens: int) -> None:
    if not key_id or key_id in ("anonymous", "env-master"):
        return
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE api_keys
            SET last_used_at = ?,
                request_count = request_count + 1,
                total_tokens = total_tokens + ?
            WHERE id = ?
            """,
            (now, max(0, int(total_tokens or 0)), key_id),
        )


# --- Model Routes CRUD ---

def list_model_routes() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM model_routes ORDER BY alias ASC").fetchall()
        return [
            {
                "alias": r["alias"],
                "target_model": r["target_model"],
                "description": r["description"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]


def get_model_routes_map() -> Dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT alias, target_model FROM model_routes").fetchall()
        return {r["alias"]: r["target_model"] for r in rows}


def upsert_model_route(alias: str, target_model: str, description: str = "") -> Dict[str, Any]:
    clean_alias = alias.strip()
    clean_target = target_model.strip()
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO model_routes (alias, target_model, description, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(alias) DO UPDATE SET
                target_model = excluded.target_model,
                description = excluded.description,
                updated_at = excluded.updated_at
            """,
            (clean_alias, clean_target, description.strip(), now),
        )
        row = conn.execute("SELECT * FROM model_routes WHERE alias = ?", (clean_alias,)).fetchone()
        return {
            "alias": row["alias"],
            "target_model": row["target_model"],
            "description": row["description"],
            "updated_at": row["updated_at"],
        }


def delete_model_route(alias: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM model_routes WHERE alias = ?", (alias.strip(),))
        return cur.rowcount > 0


# --- Request Logs & Analytics ---

def insert_request_log(
    endpoint: str,
    requested_model: Optional[str],
    resolved_model: Optional[str],
    stream: bool,
    status_code: int,
    latency_ms: int,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    api_key_id: Optional[str] = None,
    api_key_name: Optional[str] = None,
    conversation_id: Optional[str] = None,
    prompt_preview: Optional[str] = None,
    error_message: Optional[str] = None,
) -> str:
    log_id = f"req_{uuid.uuid4().hex[:12]}"
    now = int(time.time())
    preview = (prompt_preview or "")[:180]
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO request_logs (
                id, timestamp, api_key_id, api_key_name, endpoint,
                requested_model, resolved_model, stream, status_code, latency_ms,
                prompt_tokens, completion_tokens, total_tokens,
                conversation_id, prompt_preview, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log_id,
                now,
                api_key_id,
                api_key_name,
                endpoint,
                requested_model,
                resolved_model,
                1 if stream else 0,
                int(status_code),
                int(latency_ms),
                int(prompt_tokens or 0),
                int(completion_tokens or 0),
                int(total_tokens or 0),
                conversation_id,
                preview,
                error_message,
            ),
        )
    return log_id


def _row_to_log(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "timestamp": row["timestamp"],
        "api_key_id": row["api_key_id"],
        "api_key_name": row["api_key_name"],
        "endpoint": row["endpoint"],
        "requested_model": row["requested_model"],
        "resolved_model": row["resolved_model"],
        "stream": bool(row["stream"]),
        "status_code": row["status_code"],
        "latency_ms": row["latency_ms"],
        "prompt_tokens": row["prompt_tokens"],
        "completion_tokens": row["completion_tokens"],
        "total_tokens": row["total_tokens"],
        "conversation_id": row["conversation_id"],
        "prompt_preview": row["prompt_preview"],
        "error_message": row["error_message"],
    }


def list_request_logs(
    limit: int = 100,
    api_key_id: Optional[str] = None,
    model: Optional[str] = None,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if api_key_id:
        clauses.append("api_key_id = ?")
        params.append(api_key_id)
    if model:
        clauses.append("(resolved_model = ? OR requested_model = ?)")
        params.extend([model, model])
    if status == "ok":
        clauses.append("status_code < 400")
    elif status == "error":
        clauses.append("status_code >= 400")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(int(limit), 500)))

    with get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM request_logs {where_sql} ORDER BY timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [_row_to_log(r) for r in rows]


def clear_request_logs() -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM request_logs")


def get_analytics_summary() -> Dict[str, Any]:
    now = int(time.time())
    cutoff_24h = now - 86400

    with get_conn() as conn:
        agg = conn.execute(
            """
            SELECT
                COUNT(*) AS total_requests,
                SUM(CASE WHEN timestamp >= ? THEN 1 ELSE 0 END) AS requests_24h,
                SUM(CASE WHEN status_code < 400 THEN 1 ELSE 0 END) AS success_count,
                COALESCE(SUM(prompt_tokens), 0) AS prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) AS completion_tokens,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(AVG(latency_ms), 0) AS avg_latency_ms
            FROM request_logs
            """,
            (cutoff_24h,),
        ).fetchone()

        total_reqs = agg["total_requests"] or 0
        success_rate = round((agg["success_count"] / total_reqs) * 100, 1) if total_reqs > 0 else 100.0

        # Hourly buckets for the last 24h
        current_hour = (now // 3600) * 3600
        start_hour = current_hour - (23 * 3600)
        buckets: Dict[int, Dict[str, int]] = {
            start_hour + i * 3600: {"timestamp": start_hour + i * 3600, "requests": 0, "tokens": 0}
            for i in range(24)
        }
        recent_rows = conn.execute(
            "SELECT timestamp, total_tokens FROM request_logs WHERE timestamp >= ?",
            (start_hour,),
        ).fetchall()
        for r in recent_rows:
            bucket_ts = (r["timestamp"] // 3600) * 3600
            if bucket_ts in buckets:
                buckets[bucket_ts]["requests"] += 1
                buckets[bucket_ts]["tokens"] += r["total_tokens"] or 0

        hourly_activity = [buckets[start_hour + i * 3600] for i in range(24)]

        # Model breakdown
        model_rows = conn.execute(
            """
            SELECT
                COALESCE(resolved_model, 'unknown') AS model,
                COUNT(*) AS requests,
                COALESCE(SUM(total_tokens), 0) AS tokens
            FROM request_logs
            GROUP BY COALESCE(resolved_model, 'unknown')
            ORDER BY requests DESC
            """
        ).fetchall()
        model_breakdown = [
            {
                "model": r["model"],
                "requests": r["requests"],
                "tokens": r["tokens"],
                "pct": round((r["requests"] / total_reqs) * 100, 1) if total_reqs > 0 else 0.0,
            }
            for r in model_rows
        ]

        # Recent 6 logs
        recent_log_rows = conn.execute(
            "SELECT * FROM request_logs ORDER BY timestamp DESC LIMIT 6"
        ).fetchall()
        recent_logs = [_row_to_log(r) for r in recent_log_rows]

        return {
            "total_requests": total_reqs,
            "requests_24h": agg["requests_24h"] or 0,
            "success_rate": success_rate,
            "prompt_tokens": agg["prompt_tokens"] or 0,
            "completion_tokens": agg["completion_tokens"] or 0,
            "total_tokens": agg["total_tokens"] or 0,
            "avg_latency_ms": int(round(agg["avg_latency_ms"] or 0)),
            "hourly_activity": hourly_activity,
            "model_breakdown": model_breakdown,
            "recent_logs": recent_logs,
        }


# --- Persistent Multi-Turn Session Mapping ---

def get_session_conversation(session_key: str) -> Optional[str]:
    if not session_key:
        return None
    with get_conn() as conn:
        row = conn.execute(
            "SELECT conversation_id FROM sessions WHERE session_key = ?",
            (session_key.strip(),),
        ).fetchone()
        return row["conversation_id"] if row else None


def save_session_conversation(session_key: str, conversation_id: str, model: str = "") -> None:
    if not session_key or not conversation_id:
        return
    now = int(time.time())
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO sessions (session_key, conversation_id, model, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                conversation_id = excluded.conversation_id,
                model = excluded.model,
                updated_at = excluded.updated_at
            """,
            (session_key.strip(), conversation_id.strip(), model.strip(), now),
        )
