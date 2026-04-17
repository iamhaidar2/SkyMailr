"""
HTTP bridge: SkyMailr POSTs {"domain": "..."} with Authorization: Bearer <secret>.
Runs Postal via POSTAL_RAILS_RUNNER_CMD (shell) with {domain} substituted.

Example POSTAL_RAILS_RUNNER_CMD:
  docker exec -i postal-web bundle exec rails runner /opt/postal/bridge/create_domain.rb {domain}

Copy runner/create_domain.rb into the Postal container (or mount it), and set
POSTAL_ORG_PERMALINK / POSTAL_SERVER_PERMALINK on the Postal app (same as web UI URLs).
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from typing import Any

from flask import Flask, Response, request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("postal_bridge")

app = Flask(__name__)


def _secret_ok(req) -> bool:
    expected = (os.environ.get("PROVISIONING_SECRET") or "").strip()
    if not expected:
        logger.warning("PROVISIONING_SECRET is not set; refusing all requests")
        return False
    auth = req.headers.get("Authorization", "")
    m = re.match(r"Bearer\s+(.+)", auth.strip(), re.I)
    token = m.group(1).strip() if m else ""
    if token == expected:
        return True
    x = (req.headers.get("X-Provisioning-Secret") or "").strip()
    return x == expected


def _run_delete_rails(domain: str) -> tuple[int, str, str]:
    cmd_template = (os.environ.get("POSTAL_RAILS_DELETE_CMD") or "").strip()
    if not cmd_template:
        return (
            1,
            "",
            "POSTAL_RAILS_DELETE_CMD is not set (e.g. docker exec ... rails runner ... delete_domain.rb {domain})",
        )
    if "{domain}" not in cmd_template:
        return (
            1,
            "",
            "POSTAL_RAILS_DELETE_CMD must contain the literal placeholder {domain}",
        )
    cmd = cmd_template.format(domain=domain)
    logger.info("running delete: %s", cmd[:500])
    p = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("RAILS_RUNNER_TIMEOUT", "120")),
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def _run_rails(domain: str) -> tuple[int, str, str]:
    cmd_template = (os.environ.get("POSTAL_RAILS_RUNNER_CMD") or "").strip()
    if not cmd_template:
        return (
            1,
            "",
            "POSTAL_RAILS_RUNNER_CMD is not set (e.g. docker exec ... rails runner ... {domain})",
        )
    if "{domain}" not in cmd_template:
        return (
            1,
            "",
            "POSTAL_RAILS_RUNNER_CMD must contain the literal placeholder {domain}",
        )
    cmd = cmd_template.format(domain=domain)
    logger.info("running: %s", cmd[:500])
    p = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        timeout=int(os.environ.get("RAILS_RUNNER_TIMEOUT", "120")),
    )
    return p.returncode, p.stdout or "", p.stderr or ""


@app.get("/health")
def health():
    return {"status": "ok"}


@app.route("/provision", methods=["POST"])
@app.route("/", methods=["POST"])
def provision():
    if not _secret_ok(request):
        return Response(
            json.dumps({"ok": False, "error_code": "unauthorized", "error_detail": "Invalid or missing secret"}),
            status=401,
            mimetype="application/json",
        )

    body: dict[str, Any] = request.get_json(silent=True) or {}
    domain = (body.get("domain") or "").strip().lower().rstrip(".")
    if not domain:
        return Response(
            json.dumps({"ok": False, "error_code": "bad_request", "error_detail": "Missing domain"}),
            status=400,
            mimetype="application/json",
        )

    code, out, err = _run_rails(domain)
    text = (out or "").strip()
    if code != 0:
        logger.warning("runner exit=%s stderr=%s stdout=%s", code, err[:2000], text[:2000])
        # Prefer JSON line from stdout on error
        try:
            if text.startswith("{"):
                return Response(text, status=502, mimetype="application/json")
        except Exception:
            pass
        return Response(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "runner_failed",
                    "error_detail": (err or text or "rails runner failed")[:2000],
                }
            ),
            status=502,
            mimetype="application/json",
        )

    # Last line JSON (script should print one JSON object)
    line = text.splitlines()[-1] if text else ""
    if not line.startswith("{"):
        logger.error("unexpected stdout: %s", text[:2000])
        return Response(
            json.dumps({"ok": False, "error_code": "bad_output", "error_detail": "Rails runner did not return JSON"}),
            status=502,
            mimetype="application/json",
        )
    return Response(line, status=200, mimetype="application/json")


@app.route("/delete", methods=["POST"])
def delete_domain():
    if not _secret_ok(request):
        return Response(
            json.dumps({"ok": False, "error_code": "unauthorized", "error_detail": "Invalid or missing secret"}),
            status=401,
            mimetype="application/json",
        )

    body: dict[str, Any] = request.get_json(silent=True) or {}
    domain = (body.get("domain") or "").strip().lower().rstrip(".")
    if not domain:
        return Response(
            json.dumps({"ok": False, "error_code": "bad_request", "error_detail": "Missing domain"}),
            status=400,
            mimetype="application/json",
        )

    code, out, err = _run_delete_rails(domain)
    text = (out or "").strip()
    if code != 0:
        logger.warning("delete runner exit=%s stderr=%s stdout=%s", code, err[:2000], text[:2000])
        try:
            if text.startswith("{"):
                return Response(text, status=502, mimetype="application/json")
        except Exception:
            pass
        return Response(
            json.dumps(
                {
                    "ok": False,
                    "error_code": "runner_failed",
                    "error_detail": (err or text or "rails runner failed")[:2000],
                }
            ),
            status=502,
            mimetype="application/json",
        )

    line = text.splitlines()[-1] if text else ""
    if not line.startswith("{"):
        logger.error("unexpected delete stdout: %s", text[:2000])
        return Response(
            json.dumps({"ok": False, "error_code": "bad_output", "error_detail": "Rails runner did not return JSON"}),
            status=502,
            mimetype="application/json",
        )
    return Response(line, status=200, mimetype="application/json")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")
