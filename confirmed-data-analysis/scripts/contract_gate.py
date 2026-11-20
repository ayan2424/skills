#!/usr/bin/env python3
"""Validate, render, and promote confirmed-data-analysis request artifacts.

Uses only the Python standard library and implements the JSON Schema features used
by this skill's bundled schemas. It is not a general-purpose JSON Schema engine.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "references"
CAPABILITY_FILES = {
    "metric_trend": "metric-trend.schema.json",
    "dimension_compare": "dimension-compare.schema.json",
    "funnel": "funnel.schema.json",
    "retention": "retention.schema.json",
    "growth_decomposition": "growth-decomposition.schema.json",
    "anomaly_diagnosis": "anomaly-diagnosis.schema.json",
    "experiment_analysis": "experiment-analysis.schema.json",
    "experiment_sample_size": "experiment-sample-size.schema.json",
    "propensity_score_matching": "propensity-score-matching.schema.json",
    "synthetic_control": "synthetic-control.schema.json",
}


class ValidationFailure(Exception):
    pass


class SchemaStore:
    def __init__(self, schema_dir: Path):
        self.schema_dir = schema_dir.resolve()
        self.by_path: dict[Path, dict[str, Any]] = {}
        self.by_id: dict[str, Path] = {}
        for path in sorted(self.schema_dir.glob("*.schema.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            resolved = path.resolve()
            self.by_path[resolved] = data
            schema_id = data.get("$id")
            if schema_id:
                if schema_id in self.by_id:
                    raise ValidationFailure(f"duplicate schema id: {schema_id}")
                self.by_id[schema_id] = resolved

    def load(self, filename: str) -> tuple[dict[str, Any], Path]:
        path = (self.schema_dir / filename).resolve()
        if path not in self.by_path:
            raise ValidationFailure(f"schema not found: {filename}")
        return self.by_path[path], path

    def resolve_ref(self, ref: str, current_path: Path) -> tuple[Any, Path]:
        base, _, fragment = ref.partition("#")
        if not base:
            target_path = current_path
        elif base in self.by_id:
            target_path = self.by_id[base]
        else:
            target_path = (current_path.parent / base).resolve()
        if target_path not in self.by_path:
            raise ValidationFailure(f"unresolved schema reference: {ref} from {current_path.name}")
        node: Any = self.by_path[target_path]
        if fragment:
            if not fragment.startswith("/"):
                raise ValidationFailure(f"unsupported reference fragment: {ref}")
            for raw_token in fragment[1:].split("/"):
                token = raw_token.replace("~1", "/").replace("~0", "~")
                if not isinstance(node, dict) or token not in node:
                    raise ValidationFailure(f"unresolved JSON pointer: {ref}")
                node = node[token]
        return node, target_path


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return True


def validate_instance(value: Any, schema: Any, store: SchemaStore, current_path: Path, instance_path: str = "$") -> list[str]:
    if schema is True:
        return []
    if schema is False:
        return [f"{instance_path}: rejected by schema"]
    if not isinstance(schema, dict):
        return [f"{instance_path}: invalid schema node"]
    if "$ref" in schema:
        target, target_path = store.resolve_ref(schema["$ref"], current_path)
        return validate_instance(value, target, store, target_path, instance_path)

    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None:
        allowed = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_type_matches(value, item) for item in allowed):
            return [f"{instance_path}: expected type {allowed}, got {type(value).__name__}"]
    if "const" in schema and value != schema["const"]:
        errors.append(f"{instance_path}: expected constant {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{instance_path}: value {value!r} is not in enum")
    for sub_schema in schema.get("allOf", []):
        errors.extend(validate_instance(value, sub_schema, store, current_path, instance_path))
    if "oneOf" in schema:
        branch_errors = [validate_instance(value, branch, store, current_path, instance_path) for branch in schema["oneOf"]]
        matches = sum(not branch for branch in branch_errors)
        if matches != 1:
            details = "; ".join(" | ".join(branch[:2]) for branch in branch_errors if branch)
            errors.append(f"{instance_path}: expected exactly one oneOf match, got {matches}. {details}")
    if "not" in schema and not validate_instance(value, schema["not"], store, current_path, instance_path):
        errors.append(f"{instance_path}: matched a forbidden schema")
    if "if" in schema:
        condition_errors = validate_instance(value, schema["if"], store, current_path, instance_path)
        branch = schema.get("then") if not condition_errors else schema.get("else")
        if branch is not None:
            errors.extend(validate_instance(value, branch, store, current_path, instance_path))

    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{instance_path}.{key}: required field is missing")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate_instance(value[key], child_schema, store, current_path, f"{instance_path}.{key}"))
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{instance_path}.{key}: additional property is not allowed")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{instance_path}: requires at least {schema['minItems']} items")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{instance_path}: allows at most {schema['maxItems']} items")
        if schema.get("uniqueItems"):
            encoded = [json.dumps(item, ensure_ascii=False, sort_keys=True) for item in value]
            if len(encoded) != len(set(encoded)):
                errors.append(f"{instance_path}: items must be unique")
        if "items" in schema:
            for index, item in enumerate(value):
                errors.extend(validate_instance(item, schema["items"], store, current_path, f"{instance_path}[{index}]"))
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{instance_path}: string is shorter than {schema['minLength']}")
        if "pattern" in schema and re.search(schema["pattern"], value) is None:
            errors.append(f"{instance_path}: does not match pattern {schema['pattern']}")
        if schema.get("format") == "date-time":
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                errors.append(f"{instance_path}: invalid date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{instance_path}: must be >= {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{instance_path}: must be <= {schema['maximum']}")
    return errors


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_file(instance_path: Path, schema_filename: str, store: SchemaStore) -> Any:
    instance = load_json(instance_path)
    schema, schema_path = store.load(schema_filename)
    errors = validate_instance(instance, schema, store, schema_path)
    if errors:
        raise ValidationFailure("\n".join(errors))
    return instance


def validate_schemas(store: SchemaStore) -> dict[str, int | str]:
    refs = 0
    for path, schema in store.by_path.items():
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            raise ValidationFailure(f"{path.name}: unsupported or missing $schema")
        stack: list[Any] = [schema]
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                if "$ref" in node:
                    store.resolve_ref(node["$ref"], path)
                    refs += 1
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
    return {"status": "passed", "schema_count": len(store.by_path), "reference_count": refs}


def draft_gate_errors(draft: dict[str, Any], store: SchemaStore) -> list[str]:
    errors: list[str] = []
    capability = draft.get("selected_capability")
    if capability not in CAPABILITY_FILES:
        return ["selected_capability must identify one of the executable capabilities"]
    schema, schema_path = store.load(CAPABILITY_FILES[capability])
    expected_schema_id = schema["$id"]
    if draft.get("target_schema_id") != expected_schema_id:
        errors.append(f"target_schema_id must equal {expected_schema_id}")
    validation = draft.get("schema_validation", {})
    if validation.get("status") != "valid":
        errors.append("schema_validation.status must be valid")
    if validation.get("missing_required_fields"):
        errors.append("missing_required_fields must be empty")
    if validation.get("errors"):
        errors.append("schema_validation.errors must be empty")
    confirmation = draft.get("confirmation", {})
    if confirmation.get("draft_status") != "ready_for_confirmation":
        errors.append("confirmation.draft_status must be ready_for_confirmation")
    if confirmation.get("execution_allowed") is not False:
        errors.append("draft execution_allowed must be false")
    if confirmation.get("blocking_fields"):
        errors.append("confirmation.blocking_fields must be empty")
    for item in draft.get("field_provenance", []):
        field_path = item.get("field_path", "<unknown>")
        if item.get("blocking") is True:
            errors.append(f"{field_path}: field is blocking")
        if item.get("status") in {"missing", "conflict"}:
            errors.append(f"{field_path}: unresolved status {item.get('status')}")
        if item.get("status") == "inferred" and item.get("confirmation_needed") and item.get("confidence", 0) < 0.6:
            errors.append(f"{field_path}: inferred field confidence is below 0.6")
        if draft.get("interaction_mode") == "guided" and item.get("confirmation_needed") and not item.get("user_guidance"):
            errors.append(f"{field_path}: guided mode requires user_guidance for fields needing confirmation")
    errors.extend(validate_instance(draft.get("normalized_request"), schema, store, schema_path, "$.normalized_request"))
    return errors


def render_value(item: dict[str, Any]) -> str:
    if "value" not in item:
        return "未确定"
    value = item["value"]
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def confidence_label(value: float) -> str:
    if value >= 0.8:
        return f"高 ({value:.2f})"
    if value >= 0.6:
        return f"中 ({value:.2f})"
    return f"低 ({value:.2f})"


def render_draft(draft: dict[str, Any]) -> str:
    guided = draft.get("interaction_mode") == "guided" or any(item.get("user_guidance") for item in draft.get("field_provenance", []))
    if guided:
        lines = ["| 字段 | 初版值 | 这是什么意思 | 为什么需要 | 是否阻塞 | 需要确认 |", "|---|---|---|---|---|---|"]
    else:
        lines = ["| 字段 | 初版值 | 来源 | 置信度 | 是否阻塞 | 需要确认 |", "|---|---|---|---:|---|---|"]
    for item in draft.get("field_provenance", []):
        if guided:
            guidance = item.get("user_guidance", {})
            cells = [
                item.get("label", item.get("field_path", "")),
                render_value(item),
                guidance.get("plain_language", "—"),
                guidance.get("why_needed", "—"),
                "是" if item.get("blocking") else "否",
                "是" if item.get("confirmation_needed") else "否",
            ]
        else:
            cells = [
                item.get("label", item.get("field_path", "")),
                render_value(item),
                item.get("source", ""),
                confidence_label(float(item.get("confidence", 0))),
                "是" if item.get("blocking") else "否",
                "是" if item.get("confirmation_needed") else "否",
            ]
        escaped = [str(cell).replace("|", "\\|").replace("\n", " ") for cell in cells]
        lines.append("| " + " | ".join(escaped) + " |")
    if guided:
        tips: list[str] = []
        for item in draft.get("field_provenance", []):
            guidance = item.get("user_guidance", {})
            if not item.get("confirmation_needed") or not guidance:
                continue
            parts: list[str] = []
            if guidance.get("example"):
                parts.append(f"例如：{guidance['example']}")
            options = guidance.get("answer_options", [])
            if options:
                option_text = "；".join(f"{option.get('label')}（{option.get('meaning')}）" for option in options)
                parts.append(f"可选：{option_text}")
            parts.append("也可以回答“不知道”，我会说明能否从数据或配置中查到。")
            tips.append(f"- {item.get('label', item.get('field_path', ''))}：" + " ".join(parts))
        if tips:
            lines.extend(["", "填写提示：", *tips])
    questions = draft.get("confirmation", {}).get("questions", [])
    if questions:
        lines.extend(["", "待确认问题："])
        lines.extend(f"- {question}" for question in questions)
    return "\n".join(lines)


def promote(args: argparse.Namespace, store: SchemaStore) -> dict[str, Any]:
    draft = validate_file(args.draft, "request-draft.schema.json", store)
    gate_errors = draft_gate_errors(draft, store)
    if gate_errors:
        raise ValidationFailure("\n".join(gate_errors))
    changes: list[dict[str, Any]] = []
    if args.changes_json:
        changes = load_json(args.changes_json)
        if not isinstance(changes, list):
            raise ValidationFailure("changes JSON must be an array")
    contract = {
        "contract_id": args.contract_id or f"contract-{uuid.uuid4()}",
        "contract_version": args.contract_version,
        "supersedes_contract_id": args.supersedes_contract_id,
        "draft_id": draft["draft_id"],
        "selected_capability": draft["selected_capability"],
        "target_schema_id": draft["target_schema_id"],
        "confirmed_request": draft["normalized_request"],
        "field_provenance_snapshot": draft["field_provenance"],
        "confirmation": {
            "confirmed_by": "user",
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
            "confirmation_text": args.confirmation_text,
            "changes_from_draft": changes,
        },
        "locked": True,
        "execution_allowed": True,
    }
    schema, schema_path = store.load("confirmed-analysis-contract.schema.json")
    errors = validate_instance(contract, schema, store, schema_path)
    if errors:
        raise ValidationFailure("\n".join(errors))
    args.output.write_text(json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return contract


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-dir", type=Path, default=DEFAULT_SCHEMA_DIR)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate-schemas")
    check = subparsers.add_parser("check-draft")
    check.add_argument("--input", type=Path, required=True)
    render = subparsers.add_parser("render-draft")
    render.add_argument("--input", type=Path, required=True)
    validate_contract = subparsers.add_parser("validate-contract")
    validate_contract.add_argument("--input", type=Path, required=True)
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--draft", type=Path, required=True)
    promote_parser.add_argument("--confirmation-text", required=True)
    promote_parser.add_argument("--output", type=Path, required=True)
    promote_parser.add_argument("--contract-id")
    promote_parser.add_argument("--contract-version", type=int, default=1)
    promote_parser.add_argument("--supersedes-contract-id")
    promote_parser.add_argument("--changes-json", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        store = SchemaStore(args.schema_dir)
        if args.command == "validate-schemas":
            print(json.dumps(validate_schemas(store), ensure_ascii=False))
        elif args.command == "check-draft":
            draft = validate_file(args.input, "request-draft.schema.json", store)
            errors = draft_gate_errors(draft, store)
            if errors:
                raise ValidationFailure("\n".join(errors))
            print(json.dumps({"status": "ready_for_confirmation"}, ensure_ascii=False))
        elif args.command == "render-draft":
            draft = validate_file(args.input, "request-draft.schema.json", store)
            print(render_draft(draft))
        elif args.command == "validate-contract":
            validate_file(args.input, "confirmed-analysis-contract.schema.json", store)
            print(json.dumps({"status": "passed"}, ensure_ascii=False))
        elif args.command == "promote":
            contract = promote(args, store)
            print(json.dumps({"status": "promoted", "contract_id": contract["contract_id"]}, ensure_ascii=False))
        return 0
    except (OSError, json.JSONDecodeError, ValidationFailure) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
