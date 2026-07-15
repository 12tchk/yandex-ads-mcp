#!/usr/bin/env python3
"""Offline smoke tests for the fork's safety/access additions.

No network and no credentials required. Verifies:
  - mutating vs read-only tool classification
  - exact tool and account allowlists
  - write tools stay hidden and blocked unless independently armed
  - Direct vs Metrika/Wordstat classification
  - YD_LOG_FILE no longer writes a log file by default
  - partial-success annotation of Direct responses
  - tool schemas expose client_login (and confirm when YD_CONFIRM=on)

Run: python3 test_safety.py
"""
import os
import sys
import asyncio
import json
import tempfile

# Token must be present for the module to import cleanly under some setups.
os.environ.setdefault("YD_OAUTH_TOKEN", "test-token")
os.environ["YD_READONLY"] = "true"
os.environ["YD_WRITE_ARMED"] = "false"
os.environ["YD_CONFIRM"] = "true"
os.environ["YD_REQUIRE_LOGIN_ALLOWLIST"] = "true"
os.environ["YD_ALLOWED_LOGINS"] = "allowed-login"
os.environ["YD_ENABLED_TOOLS"] = ",".join([
    "yd_campaigns_get",
    "yd_campaigns_add",
    "yd_negative_keywords_sets_get",
    "yd_report",
    "yd_metrika_report",
])

import server  # noqa: E402
from tools_direct_extra import annotate_partial  # noqa: E402

failures = []


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failures.append(name)


print("== mutating classification ==")
MUTATING = [
    "yd_campaigns_add", "yd_campaigns_update", "yd_campaigns_action",
    "yd_ads_update", "yd_keyword_bids_set_auto", "yd_bid_modifiers_toggle",
    "yd_callouts_link", "yd_metrika_label_link", "yd_metrika_goal_delete",
    "yd_metrika_grant_add", "yd_metrika_upload_conversions", "yd_videos_upload",
    "yd_excluded_sites_update", "yd_blocked_ips_update", "yd_campaign_strategy_update",
]
READONLY = [
    "yd_campaigns_get", "yd_keywords_research", "yd_keywords_has_volume",
    "yd_report", "yd_changes_check", "yd_wordstat_top_requests",
    "yd_wordstat_regions_tree", "yd_metrika_report", "yd_metrika_report_comparison",
    "yd_metrika_counters_get", "yd_metrika_conversions_status",
    "yd_excluded_sites_get", "yd_regions_get", "yd_interests_get",
    "yd_negative_keywords_sets_get",
]
for n in MUTATING:
    check(f"{n} is mutating", server._is_mutating(n) is True)
for n in READONLY:
    check(f"{n} is read-only", server._is_mutating(n) is False)

print("== direct vs metrika/wordstat ==")
check("yd_campaigns_add is direct", server._is_direct("yd_campaigns_add") is True)
check("yd_vcards_add is direct", server._is_direct("yd_vcards_add") is True)
check("yd_metrika_report not direct", server._is_direct("yd_metrika_report") is False)
check("yd_wordstat_top_requests not direct", server._is_direct("yd_wordstat_top_requests") is False)

print("== logging default ==")
check("no log file written by default", server.LOG_FILE == "" and
      not os.path.exists(os.path.join(os.path.dirname(os.path.abspath(server.__file__)), "yandex-ads.log")))

print("== secret file controls ==")
saved_inline = os.environ.pop("YD_OAUTH_TOKEN", None)
saved_file = os.environ.pop("YD_OAUTH_TOKEN_FILE", None)
try:
    with tempfile.NamedTemporaryFile("w", delete=True) as token_file:
        token_file.write("file-token")
        token_file.flush()
        os.chmod(token_file.name, 0o600)
        os.environ["YD_OAUTH_TOKEN_FILE"] = token_file.name
        loaded_token, load_error = server._load_oauth_token()
        check("600 token file accepted", loaded_token == "file-token" and not load_error)
        os.chmod(token_file.name, 0o644)
        _, permission_error = server._load_oauth_token()
        check("world-readable token file rejected", "permissions" in permission_error)
finally:
    os.environ.pop("YD_OAUTH_TOKEN_FILE", None)
    if saved_inline is not None:
        os.environ["YD_OAUTH_TOKEN"] = saved_inline
    if saved_file is not None:
        os.environ["YD_OAUTH_TOKEN_FILE"] = saved_file

print("== partial-success annotation ==")
ok = annotate_partial({"result": {"AddResults": [{"Id": 1}]}})
check("clean result has no _partial_success", "_partial_success" not in ok)
bad = annotate_partial({"result": {"AddResults": [
    {"Id": 1},
    {"Errors": [{"Code": 5, "Message": "Bad text"}]},
    {"Warnings": [{"Code": 9, "Message": "Truncated"}]},
]}})
ps = bad.get("_partial_success", {})
check("errors detected", ps.get("error_count") == 1)
check("warnings detected", ps.get("warning_count") == 1)
check("ok flag false on error", ps.get("ok") is False)

print("== schema augmentation ==")
tools = {t.name: t for t in asyncio.run(server.list_tools())}
campaign_props = tools["yd_campaigns_get"].inputSchema["properties"]
campaign_required = tools["yd_campaigns_get"].inputSchema["required"]
check("direct tool exposes client_login", "client_login" in campaign_props)
check("direct tool requires client_login", "client_login" in campaign_required)
check("mutating tool hidden in read-only mode", "yd_campaigns_add" not in tools)
check("disabled tool hidden", "yd_clients_get" not in tools)
check("read tool containing '_sets' remains visible", "yd_negative_keywords_sets_get" in tools)
metrika_props = tools["yd_metrika_report"].inputSchema["properties"]
check("metrika report has no client_login", "client_login" not in metrika_props)

print("== runtime access controls ==")


def body(result):
    return json.loads(result[0].text)


missing_login = body(asyncio.run(server.call_tool("yd_campaigns_get", {})))
check("missing client_login denied", missing_login.get("denied") is True)
foreign_login = body(asyncio.run(server.call_tool(
    "yd_campaigns_get", {"client_login": "foreign-login"}
)))
check("foreign client_login denied", foreign_login.get("denied") is True)
disabled_tool = body(asyncio.run(server.call_tool(
    "yd_clients_get", {"client_login": "allowed-login"}
)))
check("tool outside allowlist denied", disabled_tool.get("denied") is True)
write_attempt = body(asyncio.run(server.call_tool(
    "yd_campaigns_add",
    {"client_login": "allowed-login", "name": "must-not-run", "confirm": True},
)))
check("write denied even with confirm", write_attempt.get("denied") is True)

original_dispatch = server._dispatch


async def fake_dispatch(name, arguments):
    return server._result({"ok": True, "tool": name, "arguments": arguments})


server._dispatch = fake_dispatch
try:
    allowed = body(asyncio.run(server.call_tool(
        "yd_campaigns_get", {"client_login": "allowed-login"}
    )))
finally:
    server._dispatch = original_dispatch
check("allowlisted read reaches dispatcher", allowed.get("ok") is True)

print("== startup validation ==")
try:
    server._validate_config()
    valid_config = True
except RuntimeError:
    valid_config = False
check("safe configuration validates", valid_config)

original_readonly = server.READONLY
original_write_armed = server.WRITE_ARMED
try:
    server.READONLY = False
    server.WRITE_ARMED = False
    try:
        server._validate_config()
        ambiguous_write_rejected = False
    except RuntimeError:
        ambiguous_write_rejected = True
finally:
    server.READONLY = original_readonly
    server.WRITE_ARMED = original_write_armed
check("ambiguous write configuration rejected", ambiguous_write_rejected)

print("== IAM expiresAt parsing ==")
from tools_direct_extra import iam_expiry  # noqa: E402
# 2026-05-30T13:00:00Z == epoch 1780146000
exp = iam_expiry({"expiresAt": "2026-05-30T13:00:00Z"}, now=0)
check("parses ISO Z to epoch (minus 60s safety)", abs(exp - (1780146000 - 60)) < 2)
exp_ns = iam_expiry({"expiresAt": "2026-05-30T13:00:00.123456789Z"}, now=0)
check("tolerates nanosecond precision", abs(exp_ns - (1780146000 - 60)) < 2)
fb = iam_expiry({}, now=1000)
check("falls back to now+11h when no expiresAt", fb == 1000 + 11 * 3600)
bad = iam_expiry({"expiresAt": "not-a-date"}, now=2000)
check("falls back on unparseable value", bad == 2000 + 11 * 3600)

print()
if failures:
    print(f"{len(failures)} FAILED: {failures}")
    sys.exit(1)
print("ALL PASSED")
