"""MCP Server main entry point for direct execution.

This module provides a direct entry point for the MCP server.
For module execution, use: python -m src.mcp_server

Supported transports:
    - stdio: Standard I/O (default, for local MCP clients)
    - http: Custom HTTP/JSON-RPC via FastAPI (legacy)
    - sse: Server-Sent Events using the native mcp library transport
    - streamable-http: Streamable HTTP (recommended for Claude Code)
"""

import asyncio
import uvicorn

from src.config.settings import get_settings
from src.mcp_server.server import AxonMCPServer
from src.utils.logging_config import configure_logging, get_logger

# Configure logging
configure_logging()
logger = get_logger(__name__)


def create_streamable_http_app():
    """Create a Starlette ASGI app with MCP streamable-http transport.

    Uses StreamableHTTPSessionManager which handles:
    - POST /mcp: JSON-RPC requests with streaming responses
    - GET /mcp: SSE stream for server-initiated messages
    - DELETE /mcp: Session termination

    This is the recommended transport for remote MCP connections.
    """
    import contextlib

    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from src.mcp_server.server import mcp as mcp_server_instance

    settings = get_settings()

    session_manager = StreamableHTTPSessionManager(
        app=mcp_server_instance,
        json_response=False,
        stateless=True,
    )

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            yield

    async def handle_health(request: Request):
        return JSONResponse({"status": "ok", "transport": "streamable-http", "server": "axon-mcp-server"})

    class _AlreadySentResponse:
        """No-op ASGI response for handlers that already wrote to send."""
        async def __call__(self, scope, receive, send):
            pass

    async def handle_mcp_request(request: Request):
        """Route handler that delegates to StreamableHTTPSessionManager."""
        await session_manager.handle_request(request.scope, request.receive, request._send)
        return _AlreadySentResponse()

    async def handle_wellknown(request: Request):
        """Return empty JSON for OAuth discovery — indicates no auth required."""
        return JSONResponse({})

    app = Starlette(
        debug=settings.debug,
        lifespan=lifespan,
        routes=[
            Route("/health", endpoint=handle_health),
            Route("/mcp", endpoint=handle_mcp_request, methods=["GET", "POST", "DELETE"]),
            Route("/.well-known/oauth-protected-resource", endpoint=handle_wellknown),
            Route("/.well-known/oauth-protected-resource/{path:path}", endpoint=handle_wellknown),
            Route("/.well-known/oauth-authorization-server", endpoint=handle_wellknown),
            Route("/.well-known/oauth-authorization-server/{path:path}", endpoint=handle_wellknown),
            Route("/.well-known/openid-configuration", endpoint=handle_wellknown),
            Route("/.well-known/openid-configuration/{path:path}", endpoint=handle_wellknown),
        ],
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            ),
        ],
    )

    return app


def create_sse_app():
    """Create a Starlette ASGI app with the native MCP SSE transport."""
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.middleware.cors import CORSMiddleware
    from starlette.routing import Mount, Route
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    from mcp.server.sse import SseServerTransport

    from src.mcp_server.server import mcp as mcp_server_instance

    settings = get_settings()

    sse_transport = SseServerTransport(settings.mcp_sse_messages_path)

    async def handle_sse(request: Request):
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
        return JSONResponse({"status": "ok", "transport": "sse", "server": "axon-mcp-server"})

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
                allow_origins=["*"],
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

        if transport == "streamable-http":
            logger.info(
                "starting_mcp_streamable_http_server",
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
            )
            AxonMCPServer()
            app = create_streamable_http_app()
            uvicorn.run(
                app,
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
                log_level=get_settings().log_level.lower(),
                access_log=True,
            )

        elif transport == "sse":
            logger.info(
                "starting_mcp_sse_server",
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
            )
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
            logger.info(
                "starting_mcp_http_server",
                host=get_settings().mcp_http_host,
                port=get_settings().mcp_http_port,
            )
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
