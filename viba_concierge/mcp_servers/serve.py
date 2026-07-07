"""FastMCP servers for the six Viba Club domains.

Each server exposes the SAME connector functions used by the in-process
agents, so MCP transport vs direct calls is a deployment choice, not a code
fork. Run any server standalone (stdio transport, ready for ADK McpToolset
or Claude Desktop):

    python -m viba_concierge.mcp_servers.serve golf
    python -m viba_concierge.mcp_servers.serve dining
    ... (tennis | pool | marina | hoa)
"""
from __future__ import annotations

import sys

from fastmcp import FastMCP

from ..core.logging import configure, get_logger
from ..core.governing_docs import ask_governing_docs
from . import connectors as c

log = get_logger("viba.mcp")

SERVER_SPECS = {
    "golf": ("golf-teesheet", "golf"),
    "tennis": ("racquet-courts", "tennis"),
    "pool": ("aquatics", "pool"),
    "marina": ("marina-slips", "marina"),
    "dining": ("dining-pos", "dining"),
    "hoa": ("hoa-portal", "hoa"),
}


def build_server(domain: str) -> FastMCP:
    if domain not in SERVER_SPECS:
        raise ValueError(f"unknown domain '{domain}'; choose from {sorted(SERVER_SPECS)}")
    server_name, tool_domain = SERVER_SPECS[domain]
    mcp = FastMCP(server_name)
    for fn in c.tools_for_domain(tool_domain):
        mcp.tool(fn)
        log.info("mcp.tool_registered", extra={"server": server_name, "tool": fn.__name__})
    if domain == "hoa":
        mcp.tool(ask_governing_docs)  # RAG lives behind the HOA portal server
    return mcp


def main() -> None:
    configure()
    domain = sys.argv[1] if len(sys.argv) > 1 else "golf"
    server = build_server(domain)
    log.info("mcp.server_starting", extra={"domain": domain})
    server.run()  # stdio transport


if __name__ == "__main__":
    main()
