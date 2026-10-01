import pytest
from backend.app.services.rule_engine import RuleEngine

def test_rule_engine_basic_operators():
    payload = {
        "issue": {
            "title": "Critical memory leak in worker",
            "body": "Server crashes when receiving large payloads"
        }
    }

    assert RuleEngine.evaluate_rule(payload, "issues", {"field": "title", "operator": "contains", "value": "leak"})
    assert not RuleEngine.evaluate_rule(payload, "issues", {"field": "title", "operator": "contains", "value": "network"})
    assert RuleEngine.evaluate_rule(payload, "issues", {"field": "title", "operator": "starts_with", "value": "critical"})
    assert RuleEngine.evaluate_rule(payload, "issues", {"field": "title", "operator": "equals", "value": "critical memory leak in worker"})

def test_rule_engine_regex_match():
    payload = {
        "pull_request": {
            "title": "fix(security): CVE-2026-9999 patch for auth bypass",
            "head": {"ref": "hotfix/cve-patch"}
        }
    }

    cond_cve = {"field": "title", "operator": "regex_match", "value": r"CVE-\d{4}-\d+"}
    assert RuleEngine.evaluate_rule(payload, "pull_request", cond_cve)

    cond_ref = {"field": "pull_request.head.ref", "operator": "regex_match", "value": r"^hotfix/.*"}
    assert RuleEngine.evaluate_rule(payload, "pull_request", cond_ref)

def test_rule_engine_in_list():
    payload = {
        "pull_request": {
            "base": {"ref": "main"}
        }
    }
    cond = {"field": "pull_request.base.ref", "operator": "in_list", "value": ["main", "master", "release"]}
    assert RuleEngine.evaluate_rule(payload, "pull_request", cond)

    cond_staging = {"field": "pull_request.base.ref", "operator": "in_list", "value": ["staging", "develop"]}
    assert not RuleEngine.evaluate_rule(payload, "pull_request", cond_staging)

def test_rule_engine_numeric_thresholds_with_ast_context():
    payload = {"pull_request": {"title": "Refactor auth"}}
    context = {"ast_risk": 75, "findings_count": 3}

    cond_risk = {"field": "ast_risk", "operator": "gt", "value": 50}
    assert RuleEngine.evaluate_rule(payload, "pull_request", cond_risk, context=context)

    cond_risk_low = {"field": "ast_risk", "operator": "lt", "value": 50}
    assert not RuleEngine.evaluate_rule(payload, "pull_request", cond_risk_low, context=context)

def test_rule_engine_compound_rules():
    payload = {
        "issue": {
            "title": "Bug in billing checkout",
            "body": "Urgent customer impact"
        }
    }

    compound = {
        "match": "all",
        "rules": [
            {"field": "title", "operator": "contains", "value": "bug"},
            {"field": "body", "operator": "contains", "value": "urgent"}
        ]
    }
    assert RuleEngine.evaluate_rule(payload, "issues", compound)

    compound_fail = {
        "match": "all",
        "rules": [
            {"field": "title", "operator": "contains", "value": "bug"},
            {"field": "body", "operator": "contains", "value": "trivial"}
        ]
    }
    assert not RuleEngine.evaluate_rule(payload, "issues", compound_fail)

    compound_any = {
        "match": "any",
        "rules": [
            {"field": "title", "operator": "contains", "value": "missing"},
            {"field": "body", "operator": "contains", "value": "urgent"}
        ]
    }
    assert RuleEngine.evaluate_rule(payload, "issues", compound_any)
