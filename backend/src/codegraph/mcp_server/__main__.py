"""MCP server entrypoint: streamable HTTP on 0.0.0.0:8765 (slice 09)."""

from __future__ import annotations

import logging

import uvicorn

from codegraph.mcp_server.server import build_app


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(build_app(), host="0.0.0.0", port=8765)


if __name__ == "__main__":
    main()
