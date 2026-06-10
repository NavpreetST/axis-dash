"""Seed DRIFT.md state into Supabase tables.
Run after tables are created: python3 /opt/aegis/scripts/seed_drift_data.py
"""
import httpx, json, os

SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SERVICE_ROLE")
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://vbjimkvainiblouofano.supabase.co")
if not SERVICE_KEY:
    # Try reading from secrets file
    import subprocess
    r = subprocess.run(["grep", "SERVICE_ROLE", os.path.expanduser("~/.config/aegis/secrets.env")],
                       capture_output=True, text=True)
    if r.returncode == 0:
        SERVICE_KEY = r.stdout.strip().split("=", 1)[1]

BASE = f"{SUPABASE_URL}/rest/v1"
HEADERS = {
    "apikey": SERVICE_KEY,
    "Authorization": f"Bearer {SERVICE_KEY}",
    "Content-Type": "application/json",
}


def upsert(table, rows, conflict_col="key"):
    """Upsert rows into table using on_conflict."""
    if not isinstance(rows, list):
        rows = [rows]
    with httpx.Client(timeout=10.0) as c:
        r = c.post(
            f"{BASE}/{table}",
            headers={**HEADERS, "Prefer": "return=representation"},
            json=rows,
            params={"on_conflict": conflict_col},
        )
    if r.status_code not in (200, 201):
        print(f"  FAIL {table}: {r.status_code} {r.text[:120]}")
        return False
    print(f"  OK {table}: {len(rows)} rows")
    return True


def seed():
    # ---- system_state (from DRIFT.md §4) ----
    print("Seeding system_state...")
    upsert("system_state", [
        {"key": "phase", "value": "Phase 1 — memory, chat, daily-use readiness"},
        {"key": "daemon_pid", "value": "405788"},
        {"key": "uptime", "value": "~Jun 10 00:12 UTC"},
        {"key": "deployed_commit", "value": "2bb4a5d"},
        {"key": "renderer_chain", "value": "gemini → nim_nano → groq → template"},
    ])

    # ---- exit_criteria (from DRIFT.md §1 + §2 checkboxes) ----
    print("Seeding exit_criteria...")
    upsert("exit_criteria", [
        {"phase": "Phase 1", "criteria": "Chat remembers context across turns (\"what was the last commit?\")", "status": "pass", "notes": "Retrieval wired into socket handler every turn"},
        {"phase": "Phase 1", "criteria": "Chat remembers user preferences and updates when they change (\"chocolate\" → \"vanilla\")", "status": "pass", "notes": "T2 semantic facts + upsert_conflict marks old fact decayed"},
        {"phase": "Phase 1", "criteria": "Stale/superseded preferences reflected correctly (not both)", "status": "pass", "notes": "Confidence-ordering + decay_t drops superseded below threshold"},
        {"phase": "Phase 1", "criteria": "Memory decay — old facts fade, recent facts win", "status": "pass", "notes": "Recency bias 30% boost/30min half-life + turn-distance multiplier; GC reaps 90d old"},
        {"phase": "Phase 1", "criteria": "Can ask \"what's going on?\" and get current session/project state", "status": "fail", "notes": "Not tested — depends on context pack wiring into socket handler"},
        {"phase": "Phase 1", "criteria": "Website: polished, responsive on mobile, usable daily without friction", "status": "pass", "notes": "AXIS dashboard live at axis-dash.vercel.app, all PRs merged"},
        {"phase": "Phase 1", "criteria": "Preference update: \"actually, vanilla now\" → \"what ice cream?\" → \"vanilla\" (not chocolate)", "status": "pass", "notes": "upsert_conflict on T2 marks old fact decayed, inserts new"},
    ])

    # ---- merged_prs (last 10 from DRIFT.md §5) ----
    print("Seeding merged_prs...")
    upsert("merged_prs", [
        {"repo": "NavpreetST/axis-dash", "pr_number": 33, "branch": "feat/mobile-responsive-audit", "title": "Mobile responsive, ForgePanel spinners, full-screen chat overlay"},
        {"repo": "NavpreetST/axis-dash", "pr_number": 30, "branch": "ci/coderabbit-gate", "title": "Gate 3 blocks on CHANGES_REQUESTED + Gate 5 aggregate"},
        {"repo": "NavpreetST/axis-dash", "pr_number": 29, "branch": "feat/post-live-polish", "title": "Post-live polish — ForgePanel hint, status dot colors, chat typing indicator"},
        {"repo": "NavpreetST/helios", "pr_number": 54, "branch": "ci/coderabbit-gate-helios", "title": "Gate 3 + Gate 5 applied to helios CI"},
        {"repo": "NavpreetST/helios", "pr_number": 53, "branch": "feat/forge-db-poller", "title": "Forge DB poller — supabase_poller.py polls tasks table every 15s"},
        {"repo": "NavpreetST/helios", "pr_number": 52, "branch": "feat/phase1-boot-wiring", "title": "Phase 1 modules wired into main.py behind feature flags"},
        {"repo": "NavpreetST/helios", "pr_number": 51, "branch": "fix/archaeology-bugs", "title": "Archaeology: model upgrade, prompt trim, dedup, truncation"},
        {"repo": "NavpreetST/helios", "pr_number": 46, "branch": "ci/backfill-coverage", "title": "Gate backfill script + coverage dashboard"},
        {"repo": "NavpreetST/helios", "pr_number": 42, "branch": "ci/supabase-gate-sync", "title": "CI gate status → Supabase sync"},
        {"repo": "NavpreetST/helios", "pr_number": 41, "branch": "feat/supabase-bridge", "title": "Supabase bridge + NIM context pack"},
    ], conflict_col="repo,pr_number")


if __name__ == "__main__":
    seed()
    print("Done.")
