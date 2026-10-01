import logging
from typing import Dict, Any, Optional, List
import httpx
from fastapi import HTTPException, status
from backend.app.core.config import settings

logger = logging.getLogger("app.services.github_auth")

class GitHubAuthService:
    """Service to handle communication with GitHub's OAuth and REST API endpoints."""

    @staticmethod
    async def exchange_code_for_token(code: str) -> Dict[str, Any]:
        """Exchanges an authorization code for GitHub access and refresh tokens."""
        url = "https://github.com/login/oauth/access_token"
        headers = {"Accept": "application/json"}
        payload = {
            "client_id": settings.GITHUB_CLIENT_ID,
            "client_secret": settings.GITHUB_CLIENT_SECRET,
            "code": code,
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code != 200:
                logger.error("GitHub token exchange failed: %s %s", response.status_code, response.text)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange authorization code with GitHub."
                )
            
            data = response.json()
            if "error" in data:
                logger.error("GitHub token exchange returned error: %s - %s", data["error"], data.get("error_description"))
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"GitHub OAuth error: {data.get('error_description', data['error'])}"
                )
            
            return data

    @staticmethod
    async def get_user_profile(access_token: str) -> Dict[str, Any]:
        """Fetches the authenticated user's profile information from GitHub."""
        url = "https://api.github.com/user"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "Darkrai-App"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                logger.error("GitHub profile request failed: %s %s", response.status_code, response.text)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to fetch GitHub profile."
                )
            return response.json()

    @staticmethod
    async def get_user_emails(access_token: str) -> List[Dict[str, Any]]:
        """Fetches the list of email addresses associated with the GitHub user profile."""
        url = "https://api.github.com/user/emails"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "Darkrai-App"
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=headers)
            if response.status_code != 200:
                # Return empty if we cannot fetch email list (fallback to public profile email)
                logger.warning("Failed to fetch GitHub emails: %s %s", response.status_code, response.text)
                return []
            return response.json()

    @classmethod
    async def get_primary_email(cls, access_token: str, profile: Dict[str, Any]) -> Optional[str]:
        """Resolves the primary validated email for the user."""
        if profile.get("email"):
            return profile["email"]

        emails = await cls.get_user_emails(access_token)
        for email_entry in emails:
            if email_entry.get("primary") and email_entry.get("verified"):
                return email_entry["email"]
        
        # Fallback to any email present
        if emails:
            return emails[0]["email"]
        return None
