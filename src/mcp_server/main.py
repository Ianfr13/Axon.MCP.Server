"""MCP Server main entry point for direct execution.

This module provides a direct entry point for the MCP server.
For module execution, use: python -m src.mcp_server

Supported transports:
    - stdio: Standard I/O (default, for local MCP clients)
    - http: Custom HTTP/JSON-RPC via FastAPI (legacy)
    - sse: Server-Sent Events using the native mcp library transport
           Exposes GET /sse (SSE stream) and POST /messages (client messages)
"""

import asyncio
import uvicorn

from src.config.settings import get_settings
from src.mcp_server.server import AxonMCPServer
from src.utils.logging_config import configure_logging, get_logger

# Configure logging
configure_logging()
logger = get_logger(__name__)


def create_sse_app():
    """Create a Starlette ASGI app with the native MCP SSE transport.

    This uses the mcp library's built-in SseServerTransport which handles
    the full MCP protocol over SSE, including:
    - GET /sse: Establishes an SSE stream for server-to-client messages
    - POST /messages: Receives client-to-server JSON-RPC messages

    The transport is stateless regarding auth — MCP_AUTH_ENABLED=false
    (default) allows unauthenticated connections for Claude Code compatibility.
    """
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Mount, Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from mcp.server.sse import SseServerTransport

    from src.mcp_server.server import mcp as mcp_server_instance

    settings = get_settings()

    # Create SSE transport — the endpoint arg is the relative path where
    # the client should POST messages back (sent via the initial SSE event).
    sse_transport = SseServerTransport(
        settings.mcp_sse_messages_path,
    )

    async def handle_sse(request: Request):
        """Handle SSE connection requests (GET /sse).

        Each connection creates a new MCP session with its own read/write
        streams. The server runs the full MCP protocol over these streams.
        """
        logger.info("mcp_sse_client_connected", client=request.client.host if request.client else "unknown")
        async with sse_transport.connect_sse(
            request.scope, request.receive, request._send
        ) as (read_stream, write_stream):
            await mcp_server_instance.run(
                read_stream,
                write_stream,
                mcp_server_instance.create_initialization_options(),
            )

    async def handle_health(request: Request):
        """Simple health check endpoint for the SSE server."""
        return JSONResponse({"status": "ok", "transport": "sse", "server": "axon-mcp-server"})

    # Build the Starlette app with the two SSE routes
    app = Starlette(
        debug=settings.debug,
        routes=[
            Route("/health", endpoint=handle_health),
            Route(settings.mcp_sse_path, endpoint=handle_sse),
            Mount(settings.mcp_sse_messages_path, app=sse_transport.handle_post_message),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=settings.api_cors_origins,
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
    )

    return app


def main():
    """Main entry point for MCP server."""
    logger.info("mcp_server_starting", transport=get_settings().mcp_transport)

    try:
        transport = get_settings().mcp_transport

        if transport == "sse":
            # Run SSE transport using native mcp library SseServerTransport
            logger.info(
                "starting_mcp_sse_server",
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
                sse_path=get_settings().mcp_sse_path,
                messages_path=get_settings().mcp_sse_messages_path,
            )

            # Initialize the AxonMCPServer to register tools/resources
            # (this populates the module-level mcp server instance via decorators)
            AxonMCPServer()

            app = create_sse_app()

            uvicorn.run(
                app,
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
                log_level=get_settings().log_level.lower(),
                access_log=True,
            )

        elif transport == "http":
            # Run HTTP transport via FastAPI (legacy custom JSON-RPC)
            logger.info(
                "starting_mcp_http_server",
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
            )

            # Import the FastAPI app that includes MCP HTTP routes
            from src.api.main import app

            uvicorn.run(
                app,
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
                log_level=get_settings().log_level.lower(),
                access_log=True,
            )

        else:
            # Run stdio transport (default)
            server = AxonMCPServer()
            asyncio.run(server.start())

    except KeyboardInterrupt:
        logger.info("mcp_server_stopped_by_user")
    except Exception as e:
        logger.error("mcp_server_failed", error=str(e), exc_info=True)
        raise


if __name__ == "__main__":
    main()
