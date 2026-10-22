"""
agent_reporter.py — reporte de ejecuciones a Supabase para agentes de AgentCore.

Copiar este archivo al repo del agente. Sin dependencias: solo stdlib.

Uso:

    import logging
    from agent_reporter import RunReporter

    log = logging.getLogger(__name__)

    with RunReporter.from_env() as run:
        repo = run.params["repository"]["full_name"]

        with run.step("npm_audit"):
            log.info("Corriendo npm audit en %s", repo)   # capturado
            findings = audit(repo)

        if not findings:
            run.succeed("no_vulnerabilities")
        else:
            with run.step("llm_fix"):
                pr = fix_and_open_pr(findings)
            run.artifact("pull_request", url=pr.url, title=pr.title)
            run.succeed("fixed", result={"fixed": len(findings)})

Variables de entorno requeridas:
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, RUN_ID
Opcional:
    RUN_PARAMS (JSON), AGENT_LOG_LEVEL (default INFO)
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

__all__ = ["RunReporter"]

MAX_MESSAGE_BYTES = 8192
FLUSH_EVERY_EVENTS = 50
FLUSH_EVERY_SECONDS = 2.0
HTTP_TIMEOUT = 10
HTTP_RETRIES = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_content_range_count(header: str | None) -> int | None:
    """Extrae la cantidad de filas afectadas del header PostgREST `Content-Range`.

    Formato: `<inicio>-<fin>/<total>` o `*/<total>` (p. ej. `0-0/1`, `*/0`).
    Devuelve el total como int, o `None` si el header falta o no se puede parsear.
    """
    if not header or "/" not in header:
        return None
    total = header.rsplit("/", 1)[1].strip()
    if not total.isdigit():
        return None
    return int(total)


def _truncate(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= MAX_MESSAGE_BYTES:
        return text
    return raw[:MAX_MESSAGE_BYTES].decode("utf-8", "ignore") + " …[truncado]"


class _SupabaseClient:
    """Cliente mínimo de PostgREST. No falla nunca hacia arriba."""

    def __init__(self, url: str, key: str) -> None:
        self.base = url.rstrip("/") + "/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=minimal",
        }

    def _request(self, method: str, path: str, payload) -> bool:
        body = json.dumps(payload, default=str).encode("utf-8")
        url = f"{self.base}{path}"
        for attempt in range(HTTP_RETRIES):
            req = urllib.request.Request(url, data=body, method=method)
            for k, v in self.headers.items():
                req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    if 200 <= resp.status < 300:
                        return True
                    detail = resp.read().decode("utf-8", "ignore")[:500]
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "ignore")[:500]
                if 400 <= exc.code < 500 and exc.code != 429:
                    break  # error de contrato: reintentar no sirve
            except Exception as exc:  # noqa: BLE001
                detail = repr(exc)
            if attempt < HTTP_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))
        # Fallback: stdout llega a CloudWatch. El reporte no puede matar al agente.
        print(f"[agent_reporter] fallo al escribir {method} {path}: {detail}", file=sys.stderr)
        print(f"[agent_reporter] payload perdido: {json.dumps(payload, default=str)[:2000]}",
              file=sys.stderr)
        return False

    def insert(self, table: str, rows) -> bool:
        return self._request("POST", f"/{table}", rows)

    def update(self, table: str, filt: str, patch: dict) -> bool:
        return self._request("PATCH", f"/{table}?{filt}", patch)

    def update_expect_rows(self, table: str, filt: str, patch: dict) -> int | None:
        """PATCH que devuelve la cantidad de filas afectadas.

        Usa `Prefer: count=exact` y lee el header `Content-Range` (p. ej.
        `0-0/1` = 1 fila, `*/0` = 0 filas). Devuelve la cantidad de filas, o
        `None` si la request falló o el conteo no pudo determinarse. No falla
        nunca hacia arriba: al igual que `_request`, un fallo cae al stderr.
        """
        url = f"{self.base}/{table}?{filt}"
        body = json.dumps(patch, default=str).encode("utf-8")
        headers = dict(self.headers)
        # headers-only evita traer el cuerpo; count=exact puebla Content-Range.
        headers["Prefer"] = "return=headers-only,count=exact"
        detail = ""
        for attempt in range(HTTP_RETRIES):
            req = urllib.request.Request(url, data=body, method="PATCH")
            for k, v in headers.items():
                req.add_header(k, v)
            try:
                with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                    if 200 <= resp.status < 300:
                        return _parse_content_range_count(resp.headers.get("Content-Range"))
                    detail = resp.read().decode("utf-8", "ignore")[:500]
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "ignore")[:500]
                if 400 <= exc.code < 500 and exc.code != 429:
                    break  # error de contrato: reintentar no sirve
            except Exception as exc:  # noqa: BLE001
                detail = repr(exc)
            if attempt < HTTP_RETRIES - 1:
                time.sleep(0.5 * (2 ** attempt))
        print(f"[agent_reporter] fallo al escribir PATCH /{table}?{filt}: {detail}", file=sys.stderr)
        return None


class _RunLogHandler(logging.Handler):
    """Redirige el logging estándar (incluidas librerías de terceros) a run_events."""

    _LEVELS = {
        logging.DEBUG: "debug",
        logging.INFO: "info",
        logging.WARNING: "warn",
        logging.ERROR: "error",
        logging.CRITICAL: "error",
    }

    def __init__(self, reporter: "RunReporter") -> None:
        super().__init__()
        self.reporter = reporter

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = self._LEVELS.get(record.levelno, "info")
            message = record.getMessage()
            if record.exc_info:
                message += "\n" + "".join(traceback.format_exception(*record.exc_info))
            self.reporter.log(message, level=level, logger=record.name)
        except Exception:  # noqa: BLE001
            pass  # nunca romper el logging de la aplicación


class _Step:
    def __init__(self, reporter: "RunReporter", step_id: str, key: str) -> None:
        self.reporter = reporter
        self.id = step_id
        self.key = key

    def __enter__(self) -> "_Step":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is None:
            self.reporter._finish_step(self.id, "succeeded")
        else:
            self.reporter._finish_step(self.id, "failed", error="".join(
                traceback.format_exception(exc_type, exc, tb)))
        return False  # re-lanza


class RunReporter:
    """Reporta el ciclo de vida de una ejecución. Usar como context manager."""

    def __init__(self, supabase_url: str, supabase_key: str, run_id: str,
                 params: dict | None = None, capture_logging: bool = True) -> None:
        self.run_id = run_id
        self.params = params or {}
        self._db = _SupabaseClient(supabase_url, supabase_key)
        self._buffer: list[dict] = []
        self._seq = 0
        self._step_seq = 0
        self._current_step_id: str | None = None
        self._last_flush = time.monotonic()
        self._terminal = False
        self._capture_logging = capture_logging
        self._handler: _RunLogHandler | None = None
        atexit.register(self.flush)

    @classmethod
    def from_env(cls, **kwargs) -> "RunReporter":
        missing = [v for v in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "RUN_ID")
                   if not os.environ.get(v)]
        if missing:
            raise RuntimeError(f"Faltan variables de entorno: {', '.join(missing)}")
        return cls(
            supabase_url=os.environ["SUPABASE_URL"],
            supabase_key=os.environ["SUPABASE_SERVICE_ROLE_KEY"],
            run_id=os.environ["RUN_ID"],
            params=json.loads(os.environ.get("RUN_PARAMS") or "{}"),
            **kwargs,
        )

    # ---------------------------------------------------------------- ciclo de vida

    def __enter__(self) -> "RunReporter":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if exc_type is not None:
            self.fail(
                error_code=exc_type.__name__,
                error_message=str(exc),
                traceback_text="".join(traceback.format_exception(exc_type, exc, tb)),
            )
        elif not self._terminal:
            # Nadie llamó succeed(). Se cierra igual para no dejar el run colgado.
            self.succeed("not_applicable")
        self._detach_logging()
        return False

    def start(self) -> None:
        affected = self._db.update_expect_rows(
            "runs", f"id=eq.{self.run_id}",
            {"status": "running", "started_at": _now()})
        if affected == 0:
            # Cero filas: no existe la fila `runs` para este run_id. El control
            # plane debe INSERTar la fila `queued` antes de invocar (D1, #100).
            # PostgREST devuelve 200 en un UPDATE sin match, así que sin este
            # aviso el run quedaría invisible y sin error. Avisar, no abortar:
            # el reporte nunca debe matar al agente.
            print(
                f"[agent_reporter] ADVERTENCIA: start() no encontró la fila runs "
                f"id={self.run_id} (0 filas afectadas). ¿El control plane INSERTó "
                f"la fila 'queued' antes de invocar? El run será invisible en "
                f"runs/v_runs. Ver issue #100.",
                file=sys.stderr,
            )
        if self._capture_logging:
            self._attach_logging()
        self.log("Ejecución iniciada.", level="info")

    def succeed(self, outcome: str, result: dict | None = None,
                metrics: dict | None = None) -> None:
        """outcome: fixed | partial | no_vulnerabilities | needs_review | not_applicable"""
        self._terminate("succeeded", outcome=outcome, result=result, metrics=metrics)

    def fail(self, error_code: str, error_message: str, outcome: str | None = None,
             traceback_text: str | None = None, metrics: dict | None = None) -> None:
        if traceback_text:
            self.log(traceback_text, level="error")
        self._terminate("failed", outcome=outcome, error_code=error_code,
                        error_message=error_message[:2000], metrics=metrics)

    def _terminate(self, status: str, outcome=None, result=None, metrics=None,
                   error_code=None, error_message=None) -> None:
        if self._terminal:
            return
        self._terminal = True
        self.log(f"Ejecución finalizada: {status}", level="info")
        self.flush()
        patch = {"status": status, "finished_at": _now()}
        if outcome is not None:
            patch["outcome"] = outcome
        if result is not None:
            patch["result"] = result
        if metrics is not None:
            patch["metrics"] = metrics
        if error_code is not None:
            patch["error_code"] = error_code
        if error_message is not None:
            patch["error_message"] = error_message
        self._db.update("runs", f"id=eq.{self.run_id}", patch)

    # ---------------------------------------------------------------- steps

    def step(self, key: str, title: str | None = None) -> _Step:
        self.flush()  # los eventos previos pertenecen al step anterior
        self._step_seq += 1
        step_id = str(uuid.uuid4())
        self._db.insert("run_steps", [{
            "id": step_id, "run_id": self.run_id, "seq": self._step_seq,
            "key": key, "title": title, "status": "running", "started_at": _now(),
        }])
        self._current_step_id = step_id
        return _Step(self, step_id, key)

    def _finish_step(self, step_id: str, status: str, error: str | None = None) -> None:
        self.flush()
        patch = {"status": status, "finished_at": _now()}
        if error:
            patch["error_message"] = error[:2000]
            self.log(error, level="error")
            self.flush()
        self._db.update("run_steps", f"id=eq.{step_id}", patch)
        if self._current_step_id == step_id:
            self._current_step_id = None

    # ---------------------------------------------------------------- eventos

    def log(self, message: str, level: str = "info", **data) -> None:
        self._seq += 1
        self._buffer.append({
            "run_id": self.run_id,
            "step_id": self._current_step_id,
            "seq": self._seq,
            "ts": _now(),
            "level": level,
            "message": _truncate(str(message)),
            "data": data or {},
        })
        if (len(self._buffer) >= FLUSH_EVERY_EVENTS
                or time.monotonic() - self._last_flush >= FLUSH_EVERY_SECONDS):
            self.flush()

    def info(self, msg, **d): self.log(msg, "info", **d)
    def warn(self, msg, **d): self.log(msg, "warn", **d)
    def error(self, msg, **d): self.log(msg, "error", **d)
    def debug(self, msg, **d): self.log(msg, "debug", **d)

    def flush(self) -> None:
        if not self._buffer:
            self._last_flush = time.monotonic()
            return
        batch, self._buffer = self._buffer, []
        self._last_flush = time.monotonic()
        self._db.insert("run_events", batch)

    # ---------------------------------------------------------------- artifacts

    def artifact(self, type_: str, url: str | None = None, title: str | None = None,
                 storage_path: str | None = None, **metadata) -> None:
        """type_: pull_request | audit_report | diff | file"""
        self._db.insert("run_artifacts", [{
            "run_id": self.run_id, "type": type_, "title": title,
            "url": url, "storage_path": storage_path, "metadata": metadata,
        }])

    # ---------------------------------------------------------------- logging estándar

    def _attach_logging(self) -> None:
        if self._handler is not None:
            return
        self._handler = _RunLogHandler(self)
        root = logging.getLogger()
        level = getattr(logging, os.environ.get("AGENT_LOG_LEVEL", "INFO").upper(), logging.INFO)
        root.setLevel(min(root.level or level, level))
        root.addHandler(self._handler)

    def _detach_logging(self) -> None:
        if self._handler is not None:
            logging.getLogger().removeHandler(self._handler)
            self._handler = None
