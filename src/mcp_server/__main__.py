"""MCP Server main entry point for running as a module.

Usage:
    python -m src.mcp_server

Delegates to src.mcp_server.main which handles transport selection
(stdio, http, sse) based on the MCP_TRANSPORT environment variable.
"""

from src.mcp_server.main import main

if __name__ == "__main__":
    main()
