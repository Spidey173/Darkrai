import pytest
from backend.app.services.ai_reviewer import AIReviewer

@pytest.mark.asyncio
async def test_ai_reviewer_clean_pr():
    clean_code = """
def update_user_email(user_id: int, new_email: str) -> bool:
    if "@" not in new_email:
        raise ValueError("Invalid email format")
    return True
"""
    result = await AIReviewer.review_pull_request(
        pr_title="feat(auth): validate email format on user profile",
        pr_body="Adds validation logic before persisting user email.",
        diff_or_code=clean_code,
        filename="auth_service.py"
    )

    assert result["is_safe"] is True
    assert result["risk_score"] == 0
    assert "Executive Summary" in result["review_comment"]
    assert "Suggested Verification Test Cases" in result["review_comment"]
    assert "kind:feature" in result["suggested_labels"]
    assert "area:auth" in result["suggested_labels"]
    assert "security:verified" in result["suggested_labels"]

@pytest.mark.asyncio
async def test_ai_reviewer_vulnerable_pr():
    vulnerable_code = """
import os

def execute_debug_hook(user_input: str):
    eval(user_input)
    os.system(f"echo {user_input}")
"""
    result = await AIReviewer.review_pull_request(
        pr_title="fix: add debug hook script",
        pr_body="Quick debug hook for system telemetry.",
        diff_or_code=vulnerable_code,
        filename="hook.py"
    )

    assert result["is_safe"] is False
    assert result["risk_score"] > 50
    assert "security:alert" in result["suggested_labels"]
    assert "review:blocker" in result["suggested_labels"]
    assert "CRITICAL" in result["review_comment"]
    assert "Block Merge" in result["review_comment"]
