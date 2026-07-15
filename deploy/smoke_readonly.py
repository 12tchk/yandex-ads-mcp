#!/usr/bin/env python3
"""Live read-only smoke test without printing client or campaign identifiers."""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


MUTATING_RE = re.compile(
    r"_(?:add|create|update|delete|action|set|toggle|link|unlink|upload)(?:_|$)"
)


def text_payload(result) -> dict:
    for content in result.content:
        text = getattr(content, "text", "")
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                continue
    return {}


async def run(login: str, env_file: str) -> dict:
    repo_dir = Path(__file__).resolve().parent.parent
    server = StdioServerParameters(
        command=str(repo_dir / "deploy" / "run-readonly.sh"),
        env={**os.environ, "YD_MCP_ENV_FILE": env_file},
    )
    async with stdio_client(server) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_tools()
            tool_names = sorted(tool.name for tool in listed.tools)
            mutating_tools = [name for name in tool_names if MUTATING_RE.search(name)]
            if mutating_tools:
                raise RuntimeError("read-only deployment exposed mutating tools")

            campaign_result = await session.call_tool(
                "yd_campaigns_get",
                arguments={"client_login": login},
            )
            if campaign_result.isError:
                raise RuntimeError("allowlisted campaign read failed")
            campaign_payload = text_payload(campaign_result)
            campaigns = campaign_payload.get("Campaigns", [])
            if not isinstance(campaigns, list):
                raise RuntimeError("Direct returned an unexpected campaigns payload")

            state_counts: dict[str, int] = {}
            for campaign in campaigns:
                state = str(campaign.get("State") or "UNKNOWN")
                state_counts[state] = state_counts.get(state, 0) + 1

            missing_login_result = await session.call_tool(
                "yd_campaigns_get",
                arguments={},
            )
            missing_login = text_payload(missing_login_result)
            foreign_login = text_payload(await session.call_tool(
                "yd_campaigns_get",
                arguments={"client_login": "not-allowlisted-smoke-login"},
            ))
            write_attempt = text_payload(await session.call_tool(
                "yd_campaigns_add",
                arguments={"client_login": login, "name": "must-not-run", "confirm": True},
            ))

            if not (missing_login_result.isError or missing_login.get("denied")):
                raise RuntimeError("missing client_login was not denied")
            if not foreign_login.get("denied"):
                raise RuntimeError("foreign client_login was not denied")
            if not write_attempt.get("denied"):
                raise RuntimeError("write attempt was not denied")

            return {
                "ok": True,
                "transport": "stdio",
                "toolCount": len(tool_names),
                "tools": tool_names,
                "campaignCount": len(campaigns),
                "campaignStates": state_counts,
                "missingLoginDenied": True,
                "foreignLoginDenied": True,
                "writeDenied": True,
            }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--client-login", required=True)
    parser.add_argument(
        "--env-file",
        default=os.environ.get("YD_MCP_ENV_FILE", ""),
    )
    args = parser.parse_args()
    if not args.env_file:
        parser.error("--env-file or YD_MCP_ENV_FILE is required")
    print(json.dumps(asyncio.run(run(args.client_login, args.env_file)), ensure_ascii=False))


if __name__ == "__main__":
    main()
