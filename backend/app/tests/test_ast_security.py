import pytest
from backend.app.services.ast_reviewer import ASTSecurityLinter

def test_ast_linter_safe_code():
    safe_code = """
def calculate_metrics(items: list[int]) -> int:
    total = sum(items)
    return total * 2

class UserProfile:
    def __init__(self, username: str):
        self.username = username
"""
    report = ASTSecurityLinter.analyze_code(safe_code, filename="safe_module.py")
    assert report.is_safe is True
    assert report.risk_score == 0
    assert report.total_findings == 0
    assert "PASS: SAFE" in report.generate_markdown_summary()

def test_ast_linter_dangerous_exec():
    unsafe_code = """
def dynamic_eval(payload: str):
    return eval(payload)

def dynamic_exec(script: str):
    exec(script)
"""
    report = ASTSecurityLinter.analyze_code(unsafe_code, filename="unsafe_exec.py")
    assert report.is_safe is False
    assert report.risk_score >= 40
    rule_ids = [f.rule_id for f in report.findings]
    assert "AST_SEC_001_DANGEROUS_EXEC" in rule_ids
    assert any(f.severity == "CRITICAL" for f in report.findings)

def test_ast_linter_shell_command_injection():
    unsafe_code = """
import os
import subprocess

def run_user_cmd(cmd: str):
    os.system(cmd)
    subprocess.Popen(f"ls {cmd}", shell=True)
"""
    report = ASTSecurityLinter.analyze_code(unsafe_code, filename="cmd_inject.py")
    assert report.is_safe is False
    rule_ids = [f.rule_id for f in report.findings]
    assert "AST_SEC_002_COMMAND_INJECTION" in rule_ids
    assert len([f for f in report.findings if f.rule_id == "AST_SEC_002_COMMAND_INJECTION"]) >= 2

def test_ast_linter_sql_injection():
    unsafe_code = """
def query_user(cursor, user_id: str):
    cursor.execute(f"SELECT * FROM users WHERE id = '{user_id}'")
"""
    report = ASTSecurityLinter.analyze_code(unsafe_code, filename="db_query.py")
    assert report.is_safe is False
    rule_ids = [f.rule_id for f in report.findings]
    assert "AST_SEC_003_SQL_INJECTION" in rule_ids
    assert any(f.severity == "HIGH" for f in report.findings)

def test_ast_linter_insecure_deserialization():
    unsafe_code = """
import pickle

def unpack_data(raw_bytes: bytes):
    return pickle.loads(raw_bytes)
"""
    report = ASTSecurityLinter.analyze_code(unsafe_code, filename="pickle_test.py")
    assert report.is_safe is False
    rule_ids = [f.rule_id for f in report.findings]
    assert "AST_SEC_004_INSECURE_DESERIALIZATION" in rule_ids

def test_ast_linter_hardcoded_secrets():
    unsafe_code = """
GITHUB_TOKEN = "ghp_1234567890abcdefghijklmnopqrstuv"
AWS_KEY = "AKIA1234567890ABCDEF"
"""
    report = ASTSecurityLinter.analyze_code(unsafe_code, filename="credentials.py")
    assert report.is_safe is False
    rule_ids = [f.rule_id for f in report.findings]
    assert "AST_SEC_005_HARDCODED_SECRET" in rule_ids

def test_ast_linter_insecure_tempfile_and_wildcard():
    code = """
import tempfile
from math import *

def make_scratch():
    path = tempfile.mktemp()
    return path
"""
    report = ASTSecurityLinter.analyze_code(code, filename="temp_test.py")
    rule_ids = [f.rule_id for f in report.findings]
    assert "AST_SEC_006_INSECURE_TEMPFILE" in rule_ids
    assert "AST_SEC_007_WILDCARD_IMPORT" in rule_ids

def test_ast_linter_syntax_error_handling():
    invalid_syntax = "def broken_code( : invalid"
    report = ASTSecurityLinter.analyze_code(invalid_syntax, filename="broken.py")
    assert report.is_safe is False
    assert report.parse_error is not None
    assert "AST_SYNTAX_ERROR" in [f.rule_id for f in report.findings]
