import ast
import re
import textwrap
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

SECRET_PATTERNS = [
    (r"ghp_[a-zA-Z0-9]{36}", "GitHub Personal Access Token", "CRITICAL"),
    (r"AKIA[0-9A-Z]{16}", "AWS Access Key ID", "CRITICAL"),
    (r"-----BEGIN (?:RSA|EC|OPENSSH|DSA|PGP)?\s?PRIVATE KEY-----", "Private Key Header", "CRITICAL"),
    (r"https://hooks\.slack\.com/services/T[a-zA-Z0-9_]+/B[a-zA-Z0-9_]+/[a-zA-Z0-9_]+", "Slack Webhook URL", "HIGH"),
    (r"(?:api[_-]?key|secret[_-]?token|auth[_-]?token)\s*=\s*['\"][a-zA-Z0-9_\-\.]{24,}['\"]", "Hardcoded API Secret", "HIGH"),
]

SUSPICIOUS_VAR_NAMES = {"api_key", "apikey", "secret_key", "private_key", "access_token", "auth_token", "db_password"}
SAFE_PLACEHOLDERS = {"placeholder", "your-key-here", "xxx", "dummy", "test", "mock", "env"}

@dataclass
class Finding:
    rule_id: str
    severity: str
    line: int
    col: int
    message: str
    snippet: str
    recommendation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity,
            "line": self.line,
            "col": self.col,
            "message": self.message,
            "snippet": self.snippet,
            "recommendation": self.recommendation
        }

@dataclass
class ASTAnalysisReport:
    filename: str
    is_safe: bool
    risk_score: int
    total_findings: int
    findings: List[Finding] = field(default_factory=list)
    analyzed_lines: int = 0
    parse_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "filename": self.filename,
            "is_safe": self.is_safe,
            "risk_score": self.risk_score,
            "total_findings": self.total_findings,
            "findings": [f.to_dict() for f in self.findings],
            "analyzed_lines": self.analyzed_lines,
            "parse_error": self.parse_error
        }

    def generate_markdown_summary(self) -> str:
        badge = "🟢 **PASS: SAFE**" if self.is_safe else "🔴 **FAIL: SECURITY ALERTS DETECTED**"
        lines = [
            f"### 🛡️ AST Static Security Analysis: `{self.filename}`",
            f"- **Status**: {badge}",
            f"- **Risk Score**: `{self.risk_score}/100`",
            f"- **Findings Detected**: `{self.total_findings}`",
            ""
        ]

        if not self.findings:
            lines.append("✅ No AST security anti-patterns or hardcoded secrets detected.")
            return "\n".join(lines)

        lines.append("| Severity | Rule | Line | Description | Recommendation |")
        lines.append("| :--- | :--- | :---: | :--- | :--- |")
        for f in self.findings:
            sev_badge = {
                "CRITICAL": "🛑 CRITICAL",
                "HIGH": "⚠️ HIGH",
                "MEDIUM": "⚡ MEDIUM",
                "LOW": "ℹ️ LOW"
            }.get(f.severity, f.severity)
            lines.append(f"| {sev_badge} | `{f.rule_id}` | L{f.line} | {f.message} | {f.recommendation} |")

        return "\n".join(lines)

class _SecurityVisitor(ast.NodeVisitor):
    def __init__(self, source_lines: List[str]):
        self.source_lines = source_lines
        self.findings: List[Finding] = []

    def _get_snippet(self, node: ast.AST) -> str:
        lineno = getattr(node, "lineno", 1)
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def visit_Call(self, node: ast.Call):
        func_name = None
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name in ("eval", "exec", "compile"):
            self.findings.append(Finding(
                rule_id="AST_SEC_001_DANGEROUS_EXEC",
                severity="CRITICAL",
                line=node.lineno,
                col=node.col_offset,
                message=f"Dangerous dynamic code execution call '{func_name}()' detected.",
                snippet=self._get_snippet(node),
                recommendation=f"Avoid dynamic '{func_name}()'. Use structured parsers (e.g. json, ast.literal_eval) instead."
            ))

        if isinstance(node.func, ast.Attribute):
            val = node.func.value
            val_id = getattr(val, "id", None)
            
            if val_id == "os" and node.func.attr in ("system", "popen"):
                self.findings.append(Finding(
                    rule_id="AST_SEC_002_COMMAND_INJECTION",
                    severity="CRITICAL",
                    line=node.lineno,
                    col=node.col_offset,
                    message=f"Insecure shell execution via 'os.{node.func.attr}()'.",
                    snippet=self._get_snippet(node),
                    recommendation="Use subprocess.run([...]) without shell=True to avoid command injection."
                ))

            if val_id == "subprocess" or node.func.attr in ("Popen", "run", "call", "check_call", "check_output"):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        self.findings.append(Finding(
                            rule_id="AST_SEC_002_COMMAND_INJECTION",
                            severity="CRITICAL",
                            line=node.lineno,
                            col=node.col_offset,
                            message=f"Subprocess invoked with 'shell=True'.",
                            snippet=self._get_snippet(node),
                            recommendation="Pass command arguments as a list with shell=False."
                        ))

            if val_id == "tempfile" and node.func.attr == "mktemp":
                self.findings.append(Finding(
                    rule_id="AST_SEC_006_INSECURE_TEMPFILE",
                    severity="MEDIUM",
                    line=node.lineno,
                    col=node.col_offset,
                    message="tempfile.mktemp() is deprecated and susceptible to symlink race conditions.",
                    snippet=self._get_snippet(node),
                    recommendation="Use tempfile.NamedTemporaryFile() or tempfile.TemporaryDirectory() instead."
                ))

            if (val_id in ("pickle", "_pickle") and node.func.attr in ("load", "loads")) or \
               (val_id == "yaml" and node.func.attr == "load"):
                is_yaml_loader_safe = False
                if val_id == "yaml":
                    for kw in node.keywords:
                        if kw.arg == "Loader" and getattr(kw.value, "attr", "") in ("SafeLoader", "CSafeLoader"):
                            is_yaml_loader_safe = True
                
                if not is_yaml_loader_safe:
                    self.findings.append(Finding(
                        rule_id="AST_SEC_004_INSECURE_DESERIALIZATION",
                        severity="HIGH",
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"Unsafe deserialization '{val_id}.{node.func.attr}()' can trigger arbitrary remote code execution.",
                        snippet=self._get_snippet(node),
                        recommendation="Use safe serialization formats like JSON, or yaml.safe_load()."
                    ))

            if node.func.attr in ("execute", "executemany"):
                if node.args:
                    first_arg = node.args[0]
                    is_formatted = (
                        isinstance(first_arg, ast.JoinedStr) or
                        (isinstance(first_arg, ast.BinOp) and isinstance(first_arg.op, ast.Mod)) or
                        (isinstance(first_arg, ast.Call) and getattr(first_arg.func, "attr", None) == "format")
                    )
                    if is_formatted:
                        self.findings.append(Finding(
                            rule_id="AST_SEC_003_SQL_INJECTION",
                            severity="HIGH",
                            line=node.lineno,
                            col=node.col_offset,
                            message="Potential raw SQL string interpolation in database execution call.",
                            snippet=self._get_snippet(node),
                            recommendation="Use parameterized queries (e.g. cursor.execute(query, (param,))) or ORM queries."
                        ))

        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        for alias in node.names:
            if alias.name == "*":
                self.findings.append(Finding(
                    rule_id="AST_SEC_007_WILDCARD_IMPORT",
                    severity="LOW",
                    line=node.lineno,
                    col=node.col_offset,
                    message=f"Wildcard import 'from {node.module} import *' pollutes namespace and obscures origin.",
                    snippet=self._get_snippet(node),
                    recommendation="Explicitly list the specific names to import."
                ))
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id.lower()
                if any(susp in var_name for susp in SUSPICIOUS_VAR_NAMES):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        val_str = node.value.value.strip()
                        if len(val_str) > 8 and not any(p in val_str.lower() for p in SAFE_PLACEHOLDERS):
                            self.findings.append(Finding(
                                rule_id="AST_SEC_005_HARDCODED_SECRET",
                                severity="HIGH",
                                line=node.lineno,
                                col=node.col_offset,
                                message=f"Suspicious hardcoded credential assigned to variable '{target.id}'.",
                                snippet=self._get_snippet(node),
                                recommendation="Store secrets in environment variables or a secrets manager."
                            ))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str):
            for pattern, pattern_name, severity in SECRET_PATTERNS:
                if re.search(pattern, node.value):
                    self.findings.append(Finding(
                        rule_id="AST_SEC_005_HARDCODED_SECRET",
                        severity=severity,
                        line=node.lineno,
                        col=node.col_offset,
                        message=f"Hardcoded {pattern_name} pattern found in string literal.",
                        snippet=self._get_snippet(node),
                        recommendation="Immediately rotate this secret and load via environment variables."
                    ))
                    break
        self.generic_visit(node)

class ASTSecurityLinter:
    """Static security analysis linter using Python's Abstract Syntax Tree (AST)."""

    @staticmethod
    def is_unified_diff(text: str) -> bool:
        """Determines if the provided code snippet is a Git unified diff / patch."""
        if not text:
            return False
        first_lines = text.strip().splitlines()[:10]
        for line in first_lines:
            if line.startswith("diff --git") or line.startswith("@@ ") or line.startswith("--- ") or line.startswith("+++ "):
                return True
        return False

    @classmethod
    def extract_python_from_diff(cls, diff_text: str) -> List[Tuple[str, str, int]]:
        """
        Parses a unified diff and extracts added/modified Python code blocks.
        Returns a list of tuples: (filename, extracted_code_block, starting_line_number).
        """
        blocks: List[Tuple[str, str, int]] = []
        current_file = "patch.py"
        is_python_file = True
        current_added_lines: List[str] = []
        hunk_start_line = 1

        lines = diff_text.splitlines()
        for line in lines:
            if line.startswith("diff --git"):
                if current_added_lines and is_python_file:
                    raw_block = "\n".join(current_added_lines)
                    dedented = textwrap.dedent(raw_block).strip()
                    if dedented:
                        blocks.append((current_file, dedented, hunk_start_line))
                current_added_lines = []

                # Extract filename from diff header
                parts = line.split()
                if len(parts) >= 4:
                    b_path = parts[3]
                    current_file = b_path[2:] if b_path.startswith("b/") else b_path
                is_python_file = current_file.endswith(".py") or not ("." in current_file)

            elif line.startswith("+++ "):
                target_path = line[4:].strip()
                if target_path.startswith("b/"):
                    current_file = target_path[2:]
                elif target_path != "/dev/null":
                    current_file = target_path
                is_python_file = current_file.endswith(".py") or not ("." in current_file)

            elif line.startswith("@@ "):
                if current_added_lines and is_python_file:
                    raw_block = "\n".join(current_added_lines)
                    dedented = textwrap.dedent(raw_block).strip()
                    if dedented:
                        blocks.append((current_file, dedented, hunk_start_line))
                current_added_lines = []

                # Extract new line start from @@ -x,y +z,w @@
                hunk_match = re.search(r"\+(\d+)", line)
                if hunk_match:
                    hunk_start_line = int(hunk_match.group(1))

            elif line.startswith("+") and not line.startswith("+++"):
                # Added line inside the hunk
                current_added_lines.append(line[1:])  # Strip leading '+'

        # Flush any trailing block
        if current_added_lines and is_python_file:
            raw_block = "\n".join(current_added_lines)
            dedented = textwrap.dedent(raw_block).strip()
            if dedented:
                blocks.append((current_file, dedented, hunk_start_line))

        return blocks

    @classmethod
    def analyze_code(cls, source_code: str, filename: str = "patch.py") -> ASTAnalysisReport:
        if not source_code or not source_code.strip():
            return ASTAnalysisReport(
                filename=filename,
                is_safe=True,
                risk_score=0,
                total_findings=0,
                findings=[],
                analyzed_lines=0
            )

        # Handle Git unified diffs by extracting added Python code blocks
        if cls.is_unified_diff(source_code):
            diff_blocks = cls.extract_python_from_diff(source_code)
            if not diff_blocks:
                # No Python additions in this diff (e.g. docs, config, or deletion-only)
                return ASTAnalysisReport(
                    filename=filename,
                    is_safe=True,
                    risk_score=0,
                    total_findings=0,
                    findings=[],
                    analyzed_lines=len(source_code.splitlines())
                )

            all_findings: List[Finding] = []
            analyzed_line_count = 0

            for file_name, code_block, start_line in diff_blocks:
                block_lines = code_block.splitlines()
                analyzed_line_count += len(block_lines)

                # Try parsing the code block as an AST tree
                tree = None
                try:
                    tree = ast.parse(code_block, filename=file_name)
                except SyntaxError:
                    # Incomplete block (e.g. return statement or inner body). Try wrapping in dummy function
                    try:
                        wrapped_code = f"def _diff_hunk_wrapper():\n{textwrap.indent(code_block, '    ')}"
                        tree = ast.parse(wrapped_code, filename=file_name)
                    except SyntaxError:
                        tree = None

                if tree:
                    visitor = _SecurityVisitor(block_lines)
                    visitor.visit(tree)
                    # Adjust line numbers relative to the diff start line
                    for f in visitor.findings:
                        adjusted_line = start_line + max(0, f.line - 1)
                        all_findings.append(Finding(
                            rule_id=f.rule_id,
                            severity=f.severity,
                            line=adjusted_line,
                            col=f.col,
                            message=f.message,
                            snippet=f.snippet,
                            recommendation=f.recommendation
                        ))
                else:
                    # Fallback line-by-line pattern matching for fragments that cannot form a complete AST
                    for idx, line in enumerate(block_lines):
                        line_num = start_line + idx
                        # Check dangerous calls
                        if re.search(r"\b(eval|exec)\s*\(", line):
                            all_findings.append(Finding(
                                rule_id="AST_SEC_001_DANGEROUS_EXEC",
                                severity="CRITICAL",
                                line=line_num,
                                col=0,
                                message="Dangerous dynamic code execution call detected in patch.",
                                snippet=line.strip(),
                                recommendation="Avoid dynamic execution. Use structured parsers instead."
                            ))
                        if re.search(r"\bos\.(system|popen)\s*\(", line) or "shell=True" in line:
                            all_findings.append(Finding(
                                rule_id="AST_SEC_002_COMMAND_INJECTION",
                                severity="CRITICAL",
                                line=line_num,
                                col=0,
                                message="Potential command injection in patch.",
                                snippet=line.strip(),
                                recommendation="Avoid shell execution with untrusted parameters."
                            ))
                        # Check hardcoded secrets
                        for pattern, pattern_name, severity in SECRET_PATTERNS:
                            if re.search(pattern, line):
                                all_findings.append(Finding(
                                rule_id="AST_SEC_005_HARDCODED_SECRET",
                                severity=severity,
                                line=line_num,
                                col=0,
                                message=f"Hardcoded {pattern_name} pattern found in patch literal.",
                                snippet=line.strip(),
                                recommendation="Immediately rotate this secret and load via environment variables."
                            ))
                            break

            weights = {"CRITICAL": 40, "HIGH": 25, "MEDIUM": 10, "LOW": 5}
            total_risk = sum(weights.get(f.severity, 5) for f in all_findings)
            risk_score = min(100, total_risk)
            is_safe = not any(f.severity in ("CRITICAL", "HIGH") for f in all_findings)

            return ASTAnalysisReport(
                filename=filename,
                is_safe=is_safe,
                risk_score=risk_score,
                total_findings=len(all_findings),
                findings=all_findings,
                analyzed_lines=analyzed_line_count
            )

        # Standard Python module analysis (standalone source file)
        lines = source_code.splitlines()
        try:
            tree = ast.parse(source_code, filename=filename)
        except SyntaxError as syn_err:
            return ASTAnalysisReport(
                filename=filename,
                is_safe=False,
                risk_score=50,
                total_findings=1,
                findings=[
                    Finding(
                        rule_id="AST_SYNTAX_ERROR",
                        severity="MEDIUM",
                        line=syn_err.lineno or 1,
                        col=syn_err.offset or 0,
                        message=f"SyntaxError parsing AST: {syn_err.msg}",
                        snippet=lines[syn_err.lineno - 1] if syn_err.lineno and syn_err.lineno <= len(lines) else "",
                        recommendation="Fix Python syntax before re-evaluating."
                    )
                ],
                analyzed_lines=len(lines),
                parse_error=str(syn_err)
            )

        visitor = _SecurityVisitor(lines)
        visitor.visit(tree)

        weights = {"CRITICAL": 40, "HIGH": 25, "MEDIUM": 10, "LOW": 5}
        total_risk = sum(weights.get(f.severity, 5) for f in visitor.findings)
        risk_score = min(100, total_risk)

        is_safe = not any(f.severity in ("CRITICAL", "HIGH") for f in visitor.findings)

        return ASTAnalysisReport(
            filename=filename,
            is_safe=is_safe,
            risk_score=risk_score,
            total_findings=len(visitor.findings),
            findings=visitor.findings,
            analyzed_lines=len(lines)
        )
