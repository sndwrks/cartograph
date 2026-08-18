"""Shared query layer — the ONLY place SQL lives.

API routers, MCP tools, and batch jobs are thin wrappers over these functions.
If a slice needs a new query, it adds a function here.
"""
