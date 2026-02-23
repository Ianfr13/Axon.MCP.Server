from typing import List, Dict, Optional

from github import Github, Auth, GithubException

from src.config.settings import get_settings
from src.utils.logging_config import get_logger
from src.utils.secrets import get_infisical_secret


logger = get_logger(__name__)


def _resolve_github_token(token: Optional[str] = None) -> str:
    """Resolve GitHub token: explicit arg > settings > Infisical."""
    if token:
        return token

    settings_token = get_settings().github_token
    if settings_token:
        return settings_token

    return get_infisical_secret("GITHUB_TOKEN")


class GitHubClient:
    """GitHub API client wrapper with authentication and error handling."""

    def __init__(self, token: Optional[str] = None, url: Optional[str] = None) -> None:
        """
        Initialize GitHub client.

        Args:
            token: GitHub personal access token (defaults to Infisical)
            url: GitHub API base URL (defaults to settings)
        """
        self.url = url or get_settings().github_url
        self.token = _resolve_github_token(token)

        if not self.token:
            raise ValueError("GitHub token is required. Configure GITHUB_TOKEN in Infisical.")

        try:
            auth = Auth.Token(self.token)
            if self.url and self.url != "https://github.com":
                # GitHub Enterprise: API is at {url}/api/v3
                base_url = f"{self.url.rstrip('/')}/api/v3"
                self.client = Github(auth=auth, base_url=base_url)
            else:
                self.client = Github(auth=auth)

            # Test authentication
            self._user = self.client.get_user()
            self._user.login  # Force API call to validate token
            logger.info("github_client_initialized", url=self.url, user=self._user.login)
        except GithubException as e:
            error_msg = f"Failed to authenticate with GitHub: {str(e)}"
            logger.error("github_authentication_failed", error=error_msg)
            raise

    def _determine_default_branch(self, repo) -> str:
        """
        Determine the default branch to use based on priority rules.

        Priority:
        1. "prd" branch if it exists
        2. "production" branch if it exists
        3. Repository's default branch

        Args:
            repo: GitHub repository object

        Returns:
            Branch name to use
        """
        try:
            branches = repo.get_branches()
            branch_names = {branch.name for branch in branches}

            if "prd" in branch_names:
                logger.info(
                    "branch_priority_selected",
                    repo=repo.full_name,
                    selected_branch="prd",
                    reason="prd_branch_exists",
                )
                return "prd"
            elif "production" in branch_names:
                logger.info(
                    "branch_priority_selected",
                    repo=repo.full_name,
                    selected_branch="production",
                    reason="production_branch_exists",
                )
                return "production"
            else:
                default = repo.default_branch or "main"
                logger.info(
                    "branch_priority_selected",
                    repo=repo.full_name,
                    selected_branch=default,
                    reason="using_repo_default",
                )
                return default
        except Exception as e:  # noqa: BLE001
            error_msg = f"Failed to list branches, using default: {str(e)}"
            logger.warning(
                "branch_list_failed_fallback",
                repo=repo.full_name,
                error=error_msg,
            )
            return repo.default_branch or "main"

    def get_project(self, full_name: str) -> Dict:
        """
        Get repository details by full name (owner/repo).

        Args:
            full_name: Repository full name (e.g., "octocat/Hello-World")

        Returns:
            Repository metadata dictionary
        """
        try:
            repo = self.client.get_repo(full_name)
            default_branch = self._determine_default_branch(repo)

            return {
                "id": repo.id,
                "name": repo.name,
                "path_with_namespace": repo.full_name,
                "http_url_to_repo": repo.clone_url,
                "clone_url": repo.clone_url,
                "default_branch": default_branch,
                "description": repo.description,
                "visibility": "private" if repo.private else "public",
                "created_at": repo.created_at.isoformat() if repo.created_at else None,
                "last_activity_at": repo.pushed_at.isoformat() if repo.pushed_at else None,
                "archived": repo.archived,
                "is_fork": repo.fork,
                "size": repo.size,
                "owner": repo.owner.login,
            }
        except GithubException as e:
            error_msg = f"Failed to get GitHub repository: {str(e)}"
            logger.error("github_repo_get_failed", full_name=full_name, error=error_msg)
            raise

    def list_org_repositories(self, org: str) -> List[Dict]:
        """
        List all repositories in a GitHub organization.

        Args:
            org: GitHub organization name

        Returns:
            List of repository metadata dictionaries
        """
        try:
            organization = self.client.get_organization(org)
            repos = organization.get_repos(type="all")

            result = []
            for repo in repos:
                if repo.archived:
                    continue

                result.append({
                    "id": repo.id,
                    "name": repo.name,
                    "path_with_namespace": repo.full_name,
                    "http_url_to_repo": repo.clone_url,
                    "clone_url": repo.clone_url,
                    "url": repo.html_url,
                    "default_branch": repo.default_branch or "main",
                    "description": repo.description,
                    "visibility": "private" if repo.private else "public",
                    "is_fork": repo.fork,
                    "is_archived": repo.archived,
                    "size": repo.size,
                    "owner": repo.owner.login,
                })

            return result
        except GithubException as e:
            error_msg = f"Failed to list GitHub org repositories: {str(e)}"
            logger.error("github_org_list_failed", org=org, error=error_msg)
            raise

    def list_user_repositories(self, username: Optional[str] = None) -> List[Dict]:
        """
        List all repositories for a user.

        Args:
            username: GitHub username (defaults to authenticated user)

        Returns:
            List of repository metadata dictionaries
        """
        try:
            authenticated_user = self.client.get_user()
            if username and username.lower() != authenticated_user.login.lower():
                # Different user — only public repos visible
                user = self.client.get_user(username)
            else:
                # Authenticated user — includes private repos
                user = authenticated_user

            repos = user.get_repos()

            result = []
            for repo in repos:
                if repo.archived:
                    continue

                result.append({
                    "id": repo.id,
                    "name": repo.name,
                    "path_with_namespace": repo.full_name,
                    "http_url_to_repo": repo.clone_url,
                    "clone_url": repo.clone_url,
                    "url": repo.html_url,
                    "default_branch": repo.default_branch or "main",
                    "description": repo.description,
                    "visibility": "private" if repo.private else "public",
                    "is_fork": repo.fork,
                    "is_archived": repo.archived,
                    "size": repo.size,
                    "owner": repo.owner.login,
                })

            return result
        except GithubException as e:
            error_msg = f"Failed to list GitHub user repositories: {str(e)}"
            logger.error("github_user_list_failed", username=username, error=error_msg)
            raise

    def get_latest_commit(self, full_name: str, branch: Optional[str] = None) -> Dict:
        """
        Get latest commit for a branch.

        Args:
            full_name: Repository full name (owner/repo)
            branch: Branch name (defaults to default_branch)

        Returns:
            Commit metadata dictionary
        """
        try:
            repo = self.client.get_repo(full_name)
            ref = branch or repo.default_branch
            commits = repo.get_commits(sha=ref)

            first_page = commits.get_page(0)
            if not first_page:
                return {}

            commit = first_page[0]
            return {
                "sha": commit.sha,
                "message": commit.commit.message,
                "author_name": commit.commit.author.name if commit.commit.author else None,
                "author_email": commit.commit.author.email if commit.commit.author else None,
                "committed_date": commit.commit.author.date.isoformat() if commit.commit.author else None,
                "title": commit.commit.message.split("\n")[0],
            }
        except GithubException as e:
            error_msg = f"Failed to get GitHub commit: {str(e)}"
            logger.error(
                "github_commit_get_failed",
                full_name=full_name,
                branch=branch,
                error=error_msg,
            )
            raise

    def list_project_files(
        self,
        full_name: str,
        path: str = "",
        ref: Optional[str] = None,
        recursive: bool = True,
    ) -> List[Dict]:
        """
        List files in a repository.

        Args:
            full_name: Repository full name (owner/repo)
            path: Directory path to list
            ref: Git ref (branch/tag/commit)
            recursive: Whether to list recursively

        Returns:
            List of file metadata dictionaries
        """
        try:
            repo = self.client.get_repo(full_name)
            ref = ref or repo.default_branch

            if recursive:
                tree = repo.get_git_tree(ref, recursive=True)
                return [
                    {
                        "path": item.path,
                        "name": item.path.split("/")[-1],
                        "type": "blob",
                        "mode": item.mode,
                        "size": item.size,
                    }
                    for item in tree.tree
                    if item.type == "blob"
                ]
            else:
                contents = repo.get_contents(path, ref=ref)
                if not isinstance(contents, list):
                    contents = [contents]
                return [
                    {
                        "path": item.path,
                        "name": item.name,
                        "type": "blob" if item.type == "file" else "tree",
                        "mode": "100644",
                        "size": item.size,
                    }
                    for item in contents
                    if item.type == "file"
                ]
        except GithubException as e:
            error_msg = f"Failed to list GitHub repository files: {str(e)}"
            logger.error(
                "github_files_list_failed",
                full_name=full_name,
                path=path,
                error=error_msg,
            )
            raise

    def get_optimal_branch_for_repository(self, full_name: str) -> str:
        """
        Get the optimal branch for a repository using priority rules.

        Args:
            full_name: Repository full name (owner/repo)

        Returns:
            Branch name to use
        """
        try:
            repo = self.client.get_repo(full_name)
            return self._determine_default_branch(repo)
        except Exception as e:  # noqa: BLE001
            error_msg = f"Failed to determine optimal branch: {str(e)}"
            logger.error(
                "optimal_branch_determination_failed",
                full_name=full_name,
                error=error_msg,
            )
            try:
                repo = self.client.get_repo(full_name)
                return repo.default_branch or "main"
            except Exception:  # noqa: BLE001
                return "main"

    def test_connection(self) -> bool:
        """
        Test GitHub connection and authentication.

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self._user.login
            logger.info("github_connection_test_successful")
            return True
        except Exception as e:  # noqa: BLE001
            error_msg = f"Failed to test GitHub connection: {str(e)}"
            logger.error("github_connection_test_failed", error=error_msg)
            return False
