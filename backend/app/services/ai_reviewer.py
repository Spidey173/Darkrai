import json
import logging
import re
from typing import Dict, Any, List, Optional
import httpx

from backend.app.core.config import settings
from backend.app.services.ast_reviewer import ASTSecurityLinter, ASTAnalysisReport

logger = logging.getLogger("app.services.ai_reviewer")

class AIReviewer:
    """
    Automated PR Code Reviewer combining AST static analysis with LLM reasoning.
    Supports Google Gemini, OpenAI, and deterministic heuristic fallback.
    """

    @classmethod
    async def review_pull_request(
        cls,
        pr_title: str,
        pr_body: str,
        diff_or_code: str,
        filename: str = "pr_patch.py"
    ) -> Dict[str, Any]:
        """
        Executes an end-to-end automated code review on a pull request.
        Returns formatted markdown comment and semantic classifications.
        """
        # 1. Run static AST security analysis
        ast_report = ASTSecurityLinter.analyze_code(diff_or_code, filename=filename)

        # 2. Extract changed functions, classes, and imports from code
        code_structure = cls._extract_code_structure(diff_or_code)

        # 3. Generate review narrative
        review_markdown = ""
        provider_used = "heuristic"

        # Try Google Gemini if configured
        if settings.GEMINI_API_KEY:
            try:
                gemini_review = await cls._generate_gemini_review(
                    pr_title, pr_body, diff_or_code, ast_report, code_structure
                )
                if gemini_review:
                    review_markdown = gemini_review
                    provider_used = "gemini"
            except Exception as e:
                logger.warning("Gemini API review generation failed: %s. Falling back.", e)

        # Try OpenAI if configured and Gemini was not used
        if not review_markdown and settings.OPENAI_API_KEY:
            try:
                openai_review = await cls._generate_openai_review(
                    pr_title, pr_body, diff_or_code, ast_report, code_structure
                )
                if openai_review:
                    review_markdown = openai_review
                    provider_used = "openai"
            except Exception as e:
                logger.warning("OpenAI API review generation failed: %s. Falling back.", e)

        # Resilient fallback: AST-grounded structured reviewer
        if not review_markdown:
            review_markdown = cls._generate_deterministic_review(
                pr_title, pr_body, ast_report, code_structure
            )
            provider_used = "ast_heuristic_engine"

        # 4. Generate semantic labels
        labels = cls._generate_semantic_labels(pr_title, pr_body, ast_report, code_structure)

        return {
            "review_comment": review_markdown,
            "provider": provider_used,
            "ast_report": ast_report.to_dict(),
            "suggested_labels": labels,
            "is_safe": ast_report.is_safe,
            "risk_score": ast_report.risk_score
        }

    @classmethod
    def _extract_code_structure(cls, code: str) -> Dict[str, Any]:
        """Extracts declared functions, classes, and imports to assess test coverage gaps."""
        functions = re.findall(r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(", code)
        classes = re.findall(r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*[:\(]", code)
        imports = re.findall(r"(?:from\s+([a-zA-Z0-9_\.]+)\s+import|import\s+([a-zA-Z0-9_\.]+))", code)
        flattened_imports = [imp[0] or imp[1] for imp in imports if (imp[0] or imp[1])]

        return {
            "functions": functions,
            "classes": classes,
            "imports": flattened_imports
        }

    @classmethod
    def _generate_semantic_labels(
        cls,
        title: str,
        body: str,
        ast_report: ASTAnalysisReport,
        structure: Dict[str, Any]
    ) -> List[str]:
        labels = set()
        title_lower = title.lower()
        body_lower = (body or "").lower()
        content = f"{title_lower} {body_lower}"

        # Security labels
        if not ast_report.is_safe or ast_report.risk_score > 30:
            labels.add("security:alert")
            labels.add("review:blocker")
        else:
            labels.add("security:verified")

        # Type labels
        if any(w in content for w in ("fix", "bug", "patch", "issue", "crash", "error")):
            labels.add("kind:bugfix")
        elif any(w in content for w in ("feat", "feature", "add", "new", "support")):
            labels.add("kind:feature")
        elif any(w in content for w in ("refactor", "cleanup", "reorganize")):
            labels.add("kind:refactor")
        elif any(w in content for w in ("test", "tests", "coverage")):
            labels.add("kind:testing")
        elif any(w in content for w in ("doc", "docs", "readme")):
            labels.add("kind:documentation")

        # Area labels
        if any(f in content for f in ("auth", "login", "oauth", "jwt", "token")):
            labels.add("area:auth")
        if any(f in content for f in ("db", "database", "sql", "migration", "alembic")):
            labels.add("area:database")
        if any(f in content for f in ("api", "endpoint", "route", "router")):
            labels.add("area:api")
        if any(f in content for f in ("queue", "worker", "redis", "celery")):
            labels.add("area:queue")

        # Missing test flag
        if structure["functions"] and not any("test" in f.lower() for f in structure["functions"]):
            if "kind:testing" not in labels:
                labels.add("tests:needed")

        return sorted(list(labels))

    @classmethod
    def _generate_deterministic_review(
        cls,
        title: str,
        body: str,
        ast_report: ASTAnalysisReport,
        structure: Dict[str, Any]
    ) -> str:
        """Constructs an enterprise-grade automated review comment from AST & metadata."""
        lines = [
            "## 🤖 Darkrai AI Automated Code Review",
            "",
            f"**PR Title:** `{title}`",
            f"**Security Verdict:** {'🟢 Clean & Compliant' if ast_report.is_safe else '🔴 Security Violations Detected'}",
            f"**AST Risk Index:** `{ast_report.risk_score} / 100`",
            "",
            "---",
            "",
            "### 📋 Executive Summary",
            f"This pull request addresses `{title}`."
        ]

        if body:
            clean_body = body.strip().replace("\n", " ")
            lines.append(f"> {clean_body[:250]}..." if len(clean_body) > 250 else f"> {clean_body}")
        lines.append("")

        # AST Report section
        lines.append(ast_report.generate_markdown_summary())
        lines.append("")

        # Code Architecture
        lines.append("### 🔍 Architectural Inspection")
        if structure["classes"]:
            lines.append(f"- **Classes Declared:** `{', '.join(structure['classes'])}`")
        if structure["functions"]:
            lines.append(f"- **Functions Introduced/Modified:** `{', '.join(structure['functions'])}`")
        if structure["imports"]:
            lines.append(f"- **Key Dependencies Referenced:** `{', '.join(structure['imports'][:6])}`")
        lines.append("")

        # Test Case Suggestions
        lines.append("### 🧪 Suggested Verification Test Cases")
        if structure["functions"]:
            for fn in structure["functions"][:4]:
                lines.append(f"- [ ] `test_{fn}_success`: Verify expected behavior with nominal inputs.")
                lines.append(f"- [ ] `test_{fn}_edge_case`: Assert robust exception handling with malformed/null inputs.")
        else:
            lines.append("- [ ] Verify unit test suite passes with complete branch coverage.")
            lines.append("- [ ] Perform regression testing on adjacent webhook handlers.")
        lines.append("")

        # Recommendations
        lines.append("### 💡 Recommended Next Actions")
        if not ast_report.is_safe:
            lines.append("1. **Block Merge:** Resolve the CRITICAL/HIGH security findings highlighted above.")
            lines.append("2. Replace dynamic execution / raw SQL calls with parameterized ORM queries.")
        else:
            lines.append("1. Ensure automated test coverage is added for newly introduced functions.")
            lines.append("2. PR meets Darkrai security compliance criteria.")

        lines.append("")
        lines.append("_Generated automatically by Darkrai Event-Driven Review Engine._")
        return "\n".join(lines)

    @classmethod
    async def _generate_gemini_review(
        cls,
        title: str,
        body: str,
        diff: str,
        ast_report: ASTAnalysisReport,
        structure: Dict[str, Any]
    ) -> Optional[str]:
        """Calls Google Gemini API using google.generativeai."""
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            prompt = f"""
You are Darkrai's senior automated staff engineer reviewing a GitHub Pull Request.
PR Title: {title}
PR Description: {body}

AST Security Findings:
{json.dumps(ast_report.to_dict(), indent=2)}

Code / Diff:
```python
{diff[:4000]}
```

Generate a thorough, professional markdown code review with:
1. Executive Summary
2. AST Security Analysis & Vulnerability Audit
3. Suggested Unit & Integration Test Cases
4. Actionable Recommendations
"""
            response = await model.generate_content_async(prompt)
            return response.text
        except Exception as e:
            logger.error("Gemini invocation error: %s", e)
            return None

    @classmethod
    async def _generate_openai_review(
        cls,
        title: str,
        body: str,
        diff: str,
        ast_report: ASTAnalysisReport,
        structure: Dict[str, Any]
    ) -> Optional[str]:
        """Calls OpenAI Chat Completion API."""
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": "gpt-4o-mini",
            "messages": [
                {
                    "role": "system",
                    "content": "You are Darkrai's senior automated staff engineer reviewing a GitHub Pull Request."
                },
                {
                    "role": "user",
                    "content": f"Review this PR:\nTitle: {title}\nBody: {body}\nAST Report: {json.dumps(ast_report.to_dict())}\nDiff:\n{diff[:4000]}"
                }
            ],
            "temperature": 0.2
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            return None
