import logging
from typing import List, Dict, Any
import httpx
from fastapi import HTTPException, status
from backend.app.core.config import settings

logger = logging.getLogger("app.services.github_client")

class GitHubClient:
    """Service client for making outbound API requests to GitHub REST APIs."""

    @staticmethod
    def _headers(access_token: str) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "Darkrai-App",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    @classmethod
    async def list_user_repos(cls, access_token: str) -> List[Dict[str, Any]]:
        """Lists repositories where the user has administrative or push access."""
        url = "https://api.github.com/user/repos?per_page=100&sort=updated"
        
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=cls._headers(access_token))
            if response.status_code != 200:
                logger.error("Failed to fetch user repositories from GitHub: %s", response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to retrieve repositories from GitHub API."
                )
            return response.json()

    @classmethod
    async def create_webhook(cls, access_token: str, owner: str, repo: str, secret: str) -> int:
        """Registers a repository webhook callback on GitHub for issues and pull requests."""
        url = f"https://api.github.com/repos/{owner}/{repo}/hooks"
        
        base_url = settings.WEBHOOK_BASE_URL.rstrip("/")
        webhook_target = f"{base_url}/api/v1/webhooks/github"
        
        payload = {
            "name": "web",
            "active": True,
            "events": ["issues", "pull_request"],
            "config": {
                "url": webhook_target,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0"
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=cls._headers(access_token), json=payload)
            if response.status_code == 201:
                data = response.json()
                return data["id"]
            
            # If 422 returned (e.g. hook already exists), look up existing hook ID
            if response.status_code == 422:
                logger.info("Hook creation returned 422, querying existing webhooks...")
                hooks_resp = await client.get(url, headers=cls._headers(access_token))
                if hooks_resp.status_code == 200:
                    for hook in hooks_resp.json():
                        if hook.get("config", {}).get("url") == webhook_target:
                            logger.info("Matched existing webhook ID: %s", hook["id"])
                            return hook["id"]

            logger.error("Failed to register webhook on GitHub: %s", response.text)
            error_detail = response.text
            try:
                err_json = response.json()
                msg = err_json.get("message", "")
                errs = err_json.get("errors", [])
                if errs and isinstance(errs, list):
                    err_msg = ", ".join([e.get("message", "") for e in errs if "message" in e])
                    error_detail = f"{msg}: {err_msg}"
                elif msg:
                    error_detail = msg
            except Exception:
                pass

            raise HTTPException(
                status_code=response.status_code,
                detail=f"GitHub hook registration failed: {error_detail}"
            )

    @classmethod
    async def delete_webhook(cls, access_token: str, owner: str, repo: str, hook_id: int) -> None:
        """Removes a repository webhook from GitHub."""
        url = f"https://api.github.com/repos/{owner}/{repo}/hooks/{hook_id}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(url, headers=cls._headers(access_token))
            # If the hook was already deleted manually on GitHub, it will return 404. We swallow it.
            if response.status_code not in (204, 404):
                logger.error("Failed to delete webhook from GitHub: %s", response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail="Failed to remove repository webhook from GitHub API."
                )

    @classmethod
    async def add_label_to_issue(
        cls, access_token: str, owner: str, repo: str, issue_number: int, label: str
    ) -> List[Dict[str, Any]]:
        """Applies a label to a GitHub issue or pull request."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/labels"
        payload = {"labels": [label]}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=cls._headers(access_token), json=payload)
            if response.status_code != 200:
                logger.error("Failed to add label: %s", response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to add label via GitHub: {response.text}"
                )
            return response.json()

    @classmethod
    async def add_comment_to_issue(
        cls, access_token: str, owner: str, repo: str, issue_number: int, body: str
    ) -> Dict[str, Any]:
        """Creates a comment response on an issue or pull request."""
        url = f"https://api.github.com/repos/{owner}/{repo}/issues/{issue_number}/comments"
        payload = {"body": body}

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=cls._headers(access_token), json=payload)
            if response.status_code != 201:
                logger.error("Failed to create issue comment: %s", response.text)
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to submit comment via GitHub: {response.text}"
                )
            return response.json()

    @classmethod
    async def fetch_pull_request_diff(cls, access_token: str, owner: str, repo: str, pull_number: int) -> str:
        """Fetches the raw unified diff for a pull request."""
        url = f"https://api.github.com/repos/{owner}/{repo}/pulls/{pull_number}"
        headers = cls._headers(access_token)
        headers["Accept"] = "application/vnd.github.v3.diff"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 200:
                return response.text
            logger.warning("Failed to fetch PR diff: %s - status %d", response.text, response.status_code)
            return ""
