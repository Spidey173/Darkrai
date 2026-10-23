import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from uuid import UUID
import httpx
from sqlalchemy import select, update, or_

from backend.app.core.config import settings
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
    owner_user: Optional[User] = None,
    worker_id: Optional[str] = None,
    lease_duration_seconds: int = 30
) -> None:
    if db is None:
        async with async_session_maker() as session:
            await _process_core(
                session, event_id, event, repository, owner_user,
                worker_id=worker_id, lease_duration_seconds=lease_duration_seconds
            )
    else:
        await _process_core(
            db, event_id, event, repository, owner_user,
            worker_id=worker_id, lease_duration_seconds=lease_duration_seconds
        )

async def _process_core(
    db: Any,
    event_id: str,
    event: Optional[WebhookEvent],
    repository: Optional[Repository],
    owner_user: Optional[User],
    worker_id: Optional[str] = None,
    lease_duration_seconds: int = 30
) -> None:
    try:
        parsed_id = event_id if isinstance(event_id, UUID) else UUID(str(event_id))
    except Exception:
        logger.error("Invalid event_id format: %s", event_id)
        return

    active_worker_id = worker_id or f"worker-{UUID(int=parsed_id.int).hex[:8]}"
    now = datetime.now(timezone.utc)
    lease_expiry = now + timedelta(seconds=lease_duration_seconds)

    # Atomic DB event claiming with explicit worker lease ownership
    # Only claim if pending/retrying, or if currently processing but lease has expired
    claim_stmt = (
        update(WebhookEvent)
        .where(
            WebhookEvent.id == parsed_id,
            or_(
                WebhookEvent.status.in_(["pending", "retrying"]),
                (WebhookEvent.status == "processing") & (WebhookEvent.lease_expires_at <= now)
            )
        )
        .values(
            status="processing",
            worker_id=active_worker_id,
            lease_expires_at=lease_expiry,
            updated_at=now
        )
    )
    claim_res = await db.execute(claim_stmt)
    await db.commit()

    if claim_res.rowcount == 0:
        chk_res = await db.execute(select(WebhookEvent).where(WebhookEvent.id == parsed_id))
        existing_evt = chk_res.scalar_one_or_none()
        st = existing_evt.status if existing_evt else "missing"
        w_id = existing_evt.worker_id if existing_evt else "none"
        exp = existing_evt.lease_expires_at.isoformat() if existing_evt and existing_evt.lease_expires_at else "none"
        logger.info(
            "Webhook event '%s' not claimable (status='%s', worker='%s', lease_expires='%s'). Skipping duplicate/concurrent execution.",
            parsed_id, st, w_id, exp
        )
        return

    # Fetch freshly claimed event
    result = await db.execute(select(WebhookEvent).where(WebhookEvent.id == parsed_id))
    event = result.scalar_one_or_none()
    if not event:
        logger.error("Webhook event '%s' not found after claiming.", parsed_id)
        return

    # Launch background lease renewal loop so slow jobs continuously hold ownership
    lease_renewal_stop = asyncio.Event()

    async def _lease_renewal_loop():
        interval = max(5.0, min(15.0, lease_duration_seconds / 2.0))
        while not lease_renewal_stop.is_set():
            try:
                await asyncio.wait_for(lease_renewal_stop.wait(), timeout=interval)
                break
            except asyncio.TimeoutError:
                pass
            
            try:
                async with async_session_maker() as renewal_session:
                    new_expiry = datetime.now(timezone.utc) + timedelta(seconds=lease_duration_seconds)
                    renew_stmt = (
                        update(WebhookEvent)
                        .where(
                            WebhookEvent.id == parsed_id,
                            WebhookEvent.worker_id == active_worker_id,
                            WebhookEvent.status == "processing"
                        )
                        .values(
                            lease_expires_at=new_expiry,
                            updated_at=datetime.now(timezone.utc)
                        )
                    )
                    await renewal_session.execute(renew_stmt)
                    await renewal_session.commit()
            except Exception as ren_err:
                logger.debug("Lease renewal tick error on event %s: %s", parsed_id, ren_err)

    renewal_task = asyncio.create_task(_lease_renewal_loop())

    try:
        # Resolve target repository and owner user to scope telemetry broadcasts
        if repository is None:
            repo_result = await db.execute(
                select(Repository).where(Repository.id == event.repository_id)
            )
            repository = repo_result.scalar_one_or_none()
        if not repository:
            raise ValueError("Associated repository details not found.")

        if owner_user is None:
            if "user" in repository.__dict__ and repository.__dict__["user"] is not None:
                owner_user = repository.user
            else:
                user_result = await db.execute(select(User).where(User.id == repository.user_id))
                owner_user = user_result.scalar_one_or_none()
        if not owner_user:
            raise ValueError("Repository owner credential record missing.")

        target_user_id = str(owner_user.id)

        await stream_broker.broadcast("event:processing_started", {
            "event_id": str(event.id),
            "event_type": event.event_type,
            "action": event.action,
            "delivery_id": str(event.delivery_id),
            "worker_id": active_worker_id
        }, user_id=target_user_id)

        if not repository.is_active:
            logger.warning("Repository '%s' is inactive. Skipping action execution.", repository.full_name)
            event.status = "completed"
            event.processed_at = datetime.now(timezone.utc)
            event.lease_expires_at = None
            await db.commit()
            return

        github_token = decrypt_token(owner_user.github_access_token_encrypted)

        if event.action not in ("opened", "synchronize", None):
            logger.info("Skipping event '%s' with non-trigger action '%s'.", event.id, event.action)
            event.status = "completed"
            event.processed_at = datetime.now(timezone.utc)
            event.lease_expires_at = None
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

        if "rules" in repository.__dict__ and repository.__dict__["rules"]:
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
                }, user_id=target_user_id)

                for action in rule.actions:
                    action_type = action.get("type")
                    action_value = action.get("value")

                    # Deterministic action idempotency key
                    action_val_repr = json.dumps(action_value, sort_keys=True) if isinstance(action_value, (dict, list)) else str(action_value)
                    action_fingerprint = f"{event.id}:{rule.id}:{action_type}:{action_val_repr}"
                    idempotency_key = hashlib.sha256(action_fingerprint.encode("utf-8")).hexdigest()

                    # Deduplication / Reconciliation: Skip side effect if already succeeded
                    duplicate_check = await db.execute(
                        select(ActionLog).where(
                            ActionLog.idempotency_key == idempotency_key,
                            ActionLog.status == "success"
                        )
                    )
                    existing_action = duplicate_check.scalar_one_or_none()
                    if existing_action:
                        logger.info(
                            "Action '%s' (key=%s) already successfully executed for event '%s'. Reconciling and skipping side effects.",
                            action_type, idempotency_key[:12], event.id
                        )
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
                            }, level="INFO" if scan_report.is_safe else "WARNING", user_id=target_user_id)

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
                            }, user_id=target_user_id)

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
                            }, user_id=target_user_id)

                        else:
                            raise ValueError(f"Unsupported action action_type: {action_type}")

                    except Exception as action_err:
                        logger.error("Failed action '%s': %s", action_type, str(action_err), exc_info=True)
                        status_str = "failed"
                        details = {"error": str(action_err)}

                    # Persist action state immediately so crashes/retries do not duplicate completed side effects
                    action_log = ActionLog(
                        webhook_event_id=event.id,
                        rule_id=rule.id,
                        action_type=action_type,
                        idempotency_key=idempotency_key,
                        status=status_str,
                        details=details
                    )
                    db.add(action_log)
                    await db.commit()

                    await stream_broker.broadcast("action:dispatched", {
                        "event_id": str(event.id),
                        "action_type": action_type,
                        "status": status_str,
                        "rule_name": rule.name
                    }, level="INFO" if status_str == "success" else "ERROR", user_id=target_user_id)

        event.status = "completed"
        event.processed_at = datetime.now(timezone.utc)
        event.lease_expires_at = None
        event.error_message = None

    except Exception as err:
        logger.error("Event processing crash on event '%s': %s", event_id, str(err), exc_info=True)
        event.retry_count = (event.retry_count or 0) + 1
        event.lease_expires_at = None
        if event.retry_count < settings.MAX_EVENT_RETRIES:
            event.status = "retrying"
        else:
            event.status = "failed"
        event.error_message = str(err)
        await stream_broker.broadcast("event:failed", {
            "event_id": str(event_id),
            "status": event.status,
            "retry_count": event.retry_count,
            "error": str(err)
        }, level="ERROR", user_id=target_user_id)
        raise

    finally:
        lease_renewal_stop.set()
        try:
            renewal_task.cancel()
            await renewal_task
        except (asyncio.CancelledError, Exception):
            pass

        await db.commit()
        await stream_broker.broadcast("event:completed", {
            "event_id": str(event_id),
            "status": event.status
        }, user_id=target_user_id)
