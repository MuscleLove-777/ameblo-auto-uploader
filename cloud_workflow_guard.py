"""Daily self-monitor for the currently authorized cloud publishing workflows."""
import json
import os
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path

PUBLISHERS = {
    "deviantart-auto-uploader": ["upload.yml"],
    "ameblo-auto-uploader": ["ameblo-post.yml"],
    "fc2-auto-uploader": ["fc2-post.yml"],
    "fc2-adult-auto-uploader": ["post.yml"],
    "hatena-auto-uploader": ["hatena-post.yml", "hatena-post-musclelove777.yml"],
}

CONTROL_STATES = {"READY", "HOLD_AUTH", "HOLD_RESULT", "HOLD_CONTENT", "HOLD_STATE", "HOLD_SOURCE",
                  "PUBLISHING", "SCRIPT_COMPLETED", "NO_WORK"}


def control_observation(path):
    """Project only allowlisted health metadata, never arbitrary file content."""
    if not path.exists():
        return None  # Legacy publisher; do not invent a controller observation.
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or data.get("schema_version") != 1
                or data.get("status") not in CONTROL_STATES
                or data.get("public_verified") is not False):
            raise ValueError("invalid control")
        run_id = str(data.get("run_id", ""))
        return {"status": data["status"], "public_verified": False,
                "run_id": run_id if run_id.isascii() and run_id.isdigit() else None}
    except (OSError, ValueError, TypeError):
        return {"status": "HOLD_STATE", "public_verified": False, "run_id": None}


def is_control_hold(control):
    return bool(control and (control["status"].startswith("HOLD_")
                             or control["status"] == "PUBLISHING"))


def api(endpoint, method="GET"):
    r = subprocess.run(["gh", "api", "--method", method, endpoint],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode:
        raise RuntimeError("GitHub API unavailable")
    return json.loads(r.stdout) if r.stdout.strip() else None


def main():
    repository = os.environ["GITHUB_REPOSITORY"]
    name = repository.split("/")[-1]
    now = datetime.now(timezone.utc)
    report = {"checked_at": now.isoformat(), "repository": repository,
              "repairs": [], "publishers": [], "issues": []}
    for workflow in PUBLISHERS[name]:
        row = {"workflow": workflow, "issues": []}
        control = control_observation(Path("publisher_state.json")) if name == "ameblo-auto-uploader" else None
        if control:
            row["publisher_control"] = control
            row["health"] = "HOLD" if is_control_hold(control) else "OBSERVED_ONLY"
            row["operator_action_required"] = is_control_hold(control) and control["status"] != "HOLD_SOURCE"
            if control["status"] == "HOLD_SOURCE":
                row["next_action"] = "recheck_source_on_existing_schedule"
        try:
            endpoint = f"repos/{repository}/actions/workflows/{workflow}"
            definition = api(endpoint)
            row["observed_state"] = definition["state"]
            if definition["state"] != "active":
                if is_control_hold(control) or definition["state"] != "disabled_inactivity":
                    # A deliberate/safety stop is not a scheduling malfunction.
                    row["issues"].append("workflow_disabled_requires_review")
                else:
                    api(endpoint + "/enable", "PUT")
                    row["current_state"] = "active"
                    report["repairs"].append("enabled:" + workflow)
            source = Path(".github/workflows") / workflow
            if not source.exists() or "schedule:" not in source.read_text(encoding="utf-8"):
                row["issues"].append("missing_publisher_schedule")
            runs = api(endpoint + "/runs?per_page=3")["workflow_runs"]
            latest = runs[0] if runs else None
            row["latest_run"] = ({k: latest.get(k) for k in
                                  ("id", "created_at", "status", "conclusion", "event")}
                                 if latest else None)
            if not latest:
                row["issues"].append("publisher_has_no_runs")
            elif latest["conclusion"] in {"failure", "timed_out", "cancelled", "action_required"}:
                # A recorded, same-run hold has already raised its first alert.
                # Keep health=HOLD visible without a second failure-mail loop.
                if not (is_control_hold(control) and control.get("run_id") == str(latest["id"])):
                    row["issues"].append("publisher_failed")
            if latest and latest["status"] != "completed" and datetime.fromisoformat(
                    latest["created_at"].replace("Z", "+00:00")) < now - timedelta(hours=2):
                row["issues"].append("publisher_run_over_2h")
            if latest and datetime.fromisoformat(latest["created_at"].replace("Z", "+00:00")) < now - timedelta(hours=48):
                row["issues"].append("publisher_stale_48h")
        except Exception as error:
            row["issues"].append("audit_unavailable:" + type(error).__name__)
        report["publishers"].append(row)
    report["health"] = "HOLD" if any(row.get("health") == "HOLD" or row["issues"]
                                        for row in report["publishers"]) else "OBSERVED_ONLY"
    report["public_verified"] = False
    Path("cloud_guard_latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    summary = "# Daily publisher self-monitor\n\n" + json.dumps(report, indent=2)
    Path(os.environ.get("GITHUB_STEP_SUMMARY", "cloud_guard_summary.md")).write_text(summary, encoding="utf-8")
    print(summary)
    return int(any(row["issues"] for row in report["publishers"]))


if __name__ == "__main__":
    raise SystemExit(main())
