import logging
import re
from typing import Dict, Any, Union, List, Optional

logger = logging.getLogger("app.services.rule_engine")

class RuleEngine:
    """
    Advanced Enterprise Rule Engine evaluating webhook payloads and AST security context.
    """

    @classmethod
    def extract_field_value(cls, payload: Dict[str, Any], event_type: str, field_path: str, context: Optional[Dict[str, Any]] = None) -> Any:
        if context and field_path in context:
            return context[field_path]

        if "." in field_path:
            parts = field_path.split(".")
            curr = payload
            for part in parts:
                if isinstance(curr, dict) and part in curr:
                    curr = curr[part]
                else:
                    return None
            return curr

        if event_type == "issues":
            issue_val = payload.get("issue", {}).get(field_path)
            if issue_val is not None:
                return issue_val
        elif event_type == "pull_request":
            pr_val = payload.get("pull_request", {}).get(field_path)
            if pr_val is not None:
                return pr_val

        return payload.get(field_path)

    @classmethod
    def evaluate_condition(cls, payload: Dict[str, Any], event_type: str, condition: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> bool:
        field = condition.get("field")
        operator = condition.get("operator")
        target_value = condition.get("value")

        if not field or not operator:
            return False

        actual_value = cls.extract_field_value(payload, event_type, field, context=context)
        if actual_value is None:
            return False

        if operator in ("gt", "gte", "lt", "lte"):
            try:
                num_actual = float(actual_value)
                num_target = float(target_value)
                if operator == "gt":
                    return num_actual > num_target
                elif operator == "gte":
                    return num_actual >= num_target
                elif operator == "lt":
                    return num_actual < num_target
                elif operator == "lte":
                    return num_actual <= num_target
            except (ValueError, TypeError):
                return False

        if operator == "regex_match":
            try:
                pattern = re.compile(str(target_value), re.IGNORECASE)
                return bool(pattern.search(str(actual_value)))
            except re.error as err:
                logger.warning("Invalid regex '%s' in rule: %s", target_value, err)
                return False

        if operator == "in_list":
            if isinstance(target_value, list):
                return str(actual_value).lower() in [str(item).lower() for item in target_value]
            return False

        if operator == "is_true":
            return bool(actual_value) is True
        if operator == "is_false":
            return bool(actual_value) is False

        actual_str = str(actual_value).lower()
        target_str = str(target_value).lower()

        if operator == "contains":
            return target_str in actual_str
        elif operator == "equals":
            return actual_str == target_str
        elif operator == "not_equals":
            return actual_str != target_str
        elif operator == "starts_with":
            return actual_str.startswith(target_str)
        elif operator == "ends_with":
            return actual_str.endswith(target_str)

        logger.warning("Unsupported operator '%s' defined in rule condition.", operator)
        return False

    @classmethod
    def evaluate_rule(
        cls,
        payload: Dict[str, Any],
        event_type: str,
        rule_conditions: Union[Dict[str, Any], List[Dict[str, Any]]],
        context: Optional[Dict[str, Any]] = None
    ) -> bool:
        if not rule_conditions:
            return True

        if isinstance(rule_conditions, dict) and "rules" in rule_conditions:
            match_mode = rule_conditions.get("match", "all").lower()
            sub_rules = rule_conditions.get("rules", [])
            if not sub_rules:
                return True
            if match_mode == "any":
                return any(cls.evaluate_condition(payload, event_type, r, context) for r in sub_rules)
            return all(cls.evaluate_condition(payload, event_type, r, context) for r in sub_rules)

        if isinstance(rule_conditions, list):
            return all(cls.evaluate_condition(payload, event_type, cond, context) for cond in rule_conditions)

        if isinstance(rule_conditions, dict):
            return cls.evaluate_condition(payload, event_type, rule_conditions, context)

        return False
