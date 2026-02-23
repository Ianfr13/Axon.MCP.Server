"""GitHub webhook endpoints for auto-sync on push."""

import hashlib
import hmac

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.dependencies import get_db_session
from src.api.services.repository_service import RepositoryService
from src.config.settings import get_settings
from src.database.models import Repository
from src.utils.logging_config import get_logger

logger = get_logger(__name__)

router = APIRouter()


def _verify_github_signature(payload_body: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature."""
    expected = "sha256=" + hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/webhooks/github", status_code=status.HTTP_200_OK)
async def github_webhook(
    request: Request,
    x_github_event: str | None = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str | None = Header(None, alias="X-Hub-Signature-256"),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Receive GitHub push events and trigger repository sync."""

    payload_body = await request.body()

    # Validate HMAC signature if secret is configured
    settings = get_settings()
    if settings.github_webhook_secret:
        if not x_hub_signature_256:
            logger.warning("github_webhook_missing_signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Hub-Signature-256 header",
            )
        if not _verify_github_signature(payload_body, x_hub_signature_256, settings.github_webhook_secret):
            logger.warning("github_webhook_invalid_signature")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid signature",
            )

    # Only process push events
    if x_github_event != "push":
        logger.debug("github_webhook_ignored_event", github_event=x_github_event)
        return {"status": "ignored", "reason": f"event '{x_github_event}' not handled"}

    payload = await request.json()

    full_name = payload.get("repository", {}).get("full_name", "")
    ref = payload.get("ref", "")
    branch = ref.removeprefix("refs/heads/")

    logger.info(
        "github_webhook_push_received",
        repository=full_name,
        ref=ref,
        branch=branch,
    )

    # Find repository in database
    stmt = select(Repository).where(Repository.path_with_namespace == full_name)
    result = await session.execute(stmt)
    repo = result.scalar_one_or_none()

    if repo is None:
        logger.info("github_webhook_repo_not_tracked", repository=full_name)
        return {"status": "ignored", "reason": "repository not tracked"}

    # Only sync if pushed branch matches default branch
    if branch != repo.default_branch:
        logger.info(
            "github_webhook_branch_mismatch",
            repository=full_name,
            pushed_branch=branch,
            default_branch=repo.default_branch,
        )
        return {"status": "ignored", "reason": f"branch '{branch}' is not default branch '{repo.default_branch}'"}

    # Trigger sync
    service = RepositoryService(session)
    sync_response = await service.trigger_sync(repo.id)

    logger.info(
        "github_webhook_sync_triggered",
        repository=full_name,
        repository_id=repo.id,
        task_id=sync_response.task_id,
    )

    return {
        "status": "sync_triggered",
        "repository_id": repo.id,
        "task_id": sync_response.task_id,
    }
