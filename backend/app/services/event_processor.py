import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import httpx
from sqlalchemy import select

from backend.app.db.session import async_session_maker
from backend.app.models.event import WebhookEvent
from backend.app.models.repository import Repository
from backend.app.models.rule import Rule
from backend.app.models.action_log import ActionLog
from backend.app.models.user import User
from backend.app.services.encryption import decrypt_token
from backend.app.services.github_client import GitHubClient
from backend.app.services.rule_engine import RuleEngine
from backend.app.services.ast_reviewer import ASTSecurityLinter
from backend.app.services.ai_reviewer import AIReviewer
from backend.app.services.event_stream import stream_broker

logger = logging.getLogger("app.services.event_processor")

async def process_webhook_event(
    event_id: str,
    db: Optional[Any] = None,
    event: Optional[WebhookEvent] = None,
    repository: Optional[Repository] = None,
    owner_user: Optional[User] = None
) -> None:
    if db is None:
        async with async_session_maker() as session:
            await _process_core(session, event_id, event, repository, owner_user)
    else:
        await _process_core(db, event_id, event, repository, owner_user)

async def _process_core(
    db: Any,
    event_id: str,
    event: Optional[WebhookEvent],
    repository: Optional[Repository],
    owner_user: Optional[User]
) -> None:
    if event is None:
        result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == event_id))
        event = result.scalar_one_or_none()
        
    if not event:
        logger.error("Webhook event '%s' not found.", event_id)
        return

    if event.status in ("completed", "processing"):
        logger.info("Webhook event '%s' is already '%s'. Skipping.", event_id, event.status)
        return

    event.status = "processing"

    await stream_broker.broadcast("event:processing_started", {
        "event_id": str(event.id),
        "event_type": event.event_type,
        "action": event.action,
        "delivery_id": str(event.delivery_id)
    })

    try:
        if repository is None:
            repo_result = await db.execute(
                select(Repository).where(Repository.id == event.repository_id)
            )
            repository = repo_result.scalar_one_or_none()
        if not repository:
            raise ValueError("Associated repository details not found.")

        if not repository.is_active:
            logger.warning("Repository '%s' is inactive. Skipping action execution.", repository.full_name)
            event.status = "completed"
            event.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        if owner_user is None:
            if hasattr(repository, "user") and repository.user is not None:
                owner_user = repository.user
            else:
                user_result = await db.execute(select(User).where(User.id == repository.user_id))
                owner_user = user_result.scalar_one_or_none()
        if not owner_user:
            raise ValueError("Repository owner credential record missing.")

        github_token = decrypt_token(owner_user.github_access_token_encrypted)

        if event.action not in ("opened", "synchronize", None):
            logger.info("Skipping event '%s' with non-trigger action '%s'.", event.id, event.action)
            event.status = "completed"
            event.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return

        payload = event.payload or {}
        number: Optional[int] = None
        title = ""
        body_text = ""
        diff_text = ""

        if event.event_type == "issues":
            issue_data = payload.get("issue", {})
            number = issue_data.get("number")
            title = issue_data.get("title", "")
            body_text = issue_data.get("body", "")
        elif event.event_type == "pull_request":
            pr_data = payload.get("pull_request", {})
            number = pr_data.get("number")
            title = pr_data.get("title", "")
            body_text = pr_data.get("body", "")

        if event.event_type == "pull_request" and number:
            try:
                diff_text = await GitHubClient.fetch_pull_request_diff(
                    github_token, repository.owner, repository.name, number
                )
            except Exception as diff_err:
                logger.warning("Could not fetch PR diff for AST review: %s", diff_err)

        ast_context = {}
        code_sample = diff_text or body_text
        if code_sample and ("def " in code_sample or "import " in code_sample or "class " in code_sample):
            ast_report = ASTSecurityLinter.analyze_code(code_sample, filename=f"PR_{number or 0}.py")
            ast_context = {
                "is_safe": ast_report.is_safe,
                "ast_risk": ast_report.risk_score,
                "findings_count": ast_report.total_findings,
                "ast_report": ast_report
            }

        if hasattr(repository, "rules") and repository.rules:
            active_rules = [r for r in repository.rules if r.event_type == event.event_type and r.is_active]
        else:
            rules_result = await db.execute(
                select(Rule).where(
                    Rule.repository_id == repository.id,
                    Rule.event_type == event.event_type,
                    Rule.is_active == True
                )
            )
            active_rules = rules_result.scalars().all()

        for rule in active_rules:
            if RuleEngine.evaluate_rule(payload, event.event_type, rule.conditions, context=ast_context):
                logger.info("Rule '%s' matched event '%s'. Executing actions.", rule.name, event.id)
                await stream_broker.broadcast("rule:matched", {
                    "rule_id": str(rule.id),
                    "rule_name": rule.name,
                    "event_id": str(event.id)
                })

                for action in rule.actions:
                    action_type = action.get("type")
                    action_value = action.get("value")

                    duplicate_check = await db.execute(
                        select(ActionLog).where(
                            ActionLog.webhook_event_id == event.id,
                            ActionLog.action_type == action_type
                        )
                    )
                    if duplicate_check.scalar_one_or_none():
                        logger.info("Action '%s' already executed for event '%s'. Skipping.", action_type, event.id)
                        continue

                    status_str = "success"
                    details: Dict[str, Any] = {}

                    try:
                        if action_type == "add_label" and number:
                            res = await GitHubClient.add_label_to_issue(
                                github_token, repository.owner, repository.name, number, action_value
                            )
                            details = {"label": action_value, "response": res}

                        elif action_type == "create_comment" and number:
                            res = await GitHubClient.add_comment_to_issue(
                                github_token, repository.owner, repository.name, number, action_value
                            )
                            details = {"comment": action_value, "response": res}

                        elif action_type == "send_slack":
                            slack_webhook_url = decrypt_token(repository.slack_webhook_url_encrypted)
                            if not slack_webhook_url:
                                raise ValueError("Slack Webhook URL is not configured on this repository.")

                            formatted_message = action_value.format(
                                number=number or "",
                                title=title,
                                repo=repository.full_name
                            )

                            async with httpx.AsyncClient(timeout=10.0) as client:
                                slack_res = await client.post(slack_webhook_url, json={"text": formatted_message})
                                if slack_res.status_code not in (200, 201, 204):
                                    raise ValueError(f"Slack API returned status {slack_res.status_code}: {slack_res.text}")
                                details = {"message": formatted_message, "status_code": slack_res.status_code}

                        elif action_type == "ast_security_scan":
                            code_to_scan = diff_text or body_text or ""
                            scan_report = ASTSecurityLinter.analyze_code(code_to_scan, filename=f"PR_{number or 'patch'}.py")
                            details = scan_report.to_dict()

                            if not scan_report.is_safe and number:
                                warning_md = scan_report.generate_markdown_summary()
                                try:
                                    await GitHubClient.add_comment_to_issue(
                                        github_token, repository.owner, repository.name, number, warning_md
                                    )
                                    await GitHubClient.add_label_to_issue(
                                        github_token, repository.owner, repository.name, number, "security:alert"
                                    )
                                except Exception as gh_err:
                                    logger.warning("Could not post AST security warning to GitHub: %s", gh_err)

                            await stream_broker.broadcast("ast_scan:completed", {
                                "event_id": str(event.id),
                                "is_safe": scan_report.is_safe,
                                "risk_score": scan_report.risk_score,
                                "findings": scan_report.total_findings
                            }, level="INFO" if scan_report.is_safe else "WARNING")

                        elif action_type == "ai_pr_review":
                            code_to_review = diff_text or body_text or ""
                            review_result = await AIReviewer.review_pull_request(
                                pr_title=title,
                                pr_body=body_text,
                                diff_or_code=code_to_review,
                                filename=f"PR_{number or 'review'}.py"
                            )
                            details = {
                                "provider": review_result["provider"],
                                "risk_score": review_result["risk_score"],
                                "suggested_labels": review_result["suggested_labels"]
                            }

                            if number:
                                try:
                                    await GitHubClient.add_comment_to_issue(
                                        github_token, repository.owner, repository.name, number,
                                        review_result["review_comment"]
                                    )
                                    for lbl in review_result["suggested_labels"]:
                                        try:
                                            await GitHubClient.add_label_to_issue(
                                                github_token, repository.owner, repository.name, number, lbl
                                            )
                                        except Exception:
                                            pass
                                except Exception as pr_post_err:
                                    logger.warning("Could not post AI review to GitHub: %s", pr_post_err)

                            await stream_broker.broadcast("ai_review:posted", {
                                "event_id": str(event.id),
                                "provider": review_result["provider"],
                                "labels": review_result["suggested_labels"]
                            })

                        elif action_type == "auto_label_semantic":
                            code_sample = diff_text or body_text or ""
                            report = ASTSecurityLinter.analyze_code(code_sample)
                            structure = AIReviewer._extract_code_structure(code_sample)
                            labels = AIReviewer._generate_semantic_labels(title, body_text, report, structure)
                            details = {"labels": labels}

                            if number:
                                for lbl in labels:
                                    try:
                                        await GitHubClient.add_label_to_issue(
                                            github_token, repository.owner, repository.name, number, lbl
                                        )
                                    except Exception:
                                        pass

                            await stream_broker.broadcast("labels:applied", {
                                "event_id": str(event.id),
                                "labels": labels
                            })

                        else:
                            raise ValueError(f"Unsupported action action_type: {action_type}")

                    except Exception as action_err:
                        logger.error("Failed action '%s': %s", action_type, str(action_err), exc_info=True)
                        status_str = "failed"
                        details = {"error": str(action_err)}

                    action_log = ActionLog(
                        webhook_event_id=event.id,
                        rule_id=rule.id,
                        action_type=action_type,
                        status=status_str,
                        details=details
                    )
                    db.add(action_log)

                    await stream_broker.broadcast("action:dispatched", {
                        "event_id": str(event.id),
                        "action_type": action_type,
                        "status": status_str,
                        "rule_name": rule.name
                    }, level="INFO" if status_str == "success" else "ERROR")

        event.status = "completed"
        event.processed_at = datetime.now(timezone.utc)
        event.error_message = None

    except Exception as err:
        logger.error("Event processing crash on event '%s': %s", event_id, str(err), exc_info=True)
        event.status = "failed"
        event.error_message = str(err)
        await stream_broker.broadcast("event:failed", {
            "event_id": str(event_id),
            "error": str(err)
        }, level="ERROR")
        raise

    finally:
        await db.commit()
        await stream_broker.broadcast("event:completed", {
            "event_id": str(event_id),
            "status": event.status
        })
