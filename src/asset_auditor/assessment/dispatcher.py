"""Assessment dispatcher — orchestrates rule evaluation per asset.

Handles:
- Eligibility / lineage resolution
- Frozen context loading
- All-rules evaluation (no short-circuit)
- Readiness derivation
- Input revalidation before commit
- Per-asset atomic transactions
- Batch lifecycle
"""
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from ..config import ASSESSOR_VERSION, ANALYSIS_SCHEMA_VERSION, PREVIEW_SCHEMA_VERSION
from .models import (
    AssessmentDecision, EvaluationOutcome, ReadinessStatus,
    StagedIssue, AssessmentResult, Lineage,
)
from .lineage import resolve_asset_lineage, compute_input_signature
from .context import load_assessment_context
from .repository import AssessmentRepository
from .evaluators import EVALUATOR_REGISTRY
from .rules import load_ruleset_with_hash, get_enabled_rules

logger = logging.getLogger(__name__)


def derive_readiness(issues: List[StagedIssue]) -> str:
    """Derive readiness status from the full set of triggered issues.

    Precedence:
      NOT_SELLABLE > NEEDS_FIX > READY_WITH_WARNINGS > READY
    """
    has_not_sellable = any(i.disposition == "NOT_SELLABLE" for i in issues)
    has_needs_fix = any(i.disposition == "NEEDS_FIX" for i in issues)
    has_warning = any(i.severity == "WARNING" for i in issues)

    if has_not_sellable:
        return ReadinessStatus.NOT_SELLABLE.value
    if has_needs_fix:
        return ReadinessStatus.NEEDS_FIX.value
    if has_warning:
        return ReadinessStatus.READY_WITH_WARNINGS.value
    return ReadinessStatus.READY.value


def evaluate_asset(
    conn: sqlite3.Connection,
    lineage: Lineage,
    ruleset_data: Dict[str, Any],
) -> AssessmentResult:
    """Run all enabled rules against frozen context. No short-circuit."""
    ctx = load_assessment_context(conn, lineage)
    enabled = get_enabled_rules(ruleset_data)

    all_issues: List[StagedIssue] = []
    rule_outcomes: Dict[str, str] = {}

    for rule_code, rule_cfg in enabled.items():
        evaluator = EVALUATOR_REGISTRY.get(rule_code)
        if not evaluator:
            logger.warning("No evaluator for rule %s, skipping", rule_code)
            rule_outcomes[rule_code] = "MISSING_EVALUATOR"
            continue

        config = rule_cfg.get("config", {})
        evals = evaluator(ctx, config)

        # Determine aggregate outcome for this rule
        triggered = [e for e in evals if e.outcome == EvaluationOutcome.TRIGGERED]
        not_applicable = all(e.outcome == EvaluationOutcome.NOT_APPLICABLE for e in evals)

        if not_applicable:
            rule_outcomes[rule_code] = "NOT_APPLICABLE"
        elif triggered:
            rule_outcomes[rule_code] = "TRIGGERED"
            # Build issues from config-authoritative severity/disposition
            severity = rule_cfg.get("severity", "INFO")
            disposition = rule_cfg.get("disposition", "NONE")
            category = rule_cfg.get("category", "")
            msg_template = rule_cfg.get("message_template", rule_code)

            for ev in triggered:
                # Format message
                fmt_ctx = {}
                if ev.observed_value:
                    fmt_ctx.update(ev.observed_value)
                if ev.message_context:
                    fmt_ctx["context"] = ev.message_context
                try:
                    message = msg_template.format(**fmt_ctx)
                except (KeyError, IndexError):
                    message = msg_template

                all_issues.append(StagedIssue(
                    rule_code=rule_code,
                    severity=severity,
                    disposition=disposition,
                    category=category,
                    message=message,
                    observed_value=ev.observed_value,
                    expected_value=ev.expected_value,
                    subject_type=ev.subject_type,
                    subject_key=ev.subject_key,
                ))
        else:
            rule_outcomes[rule_code] = "PASS"

    readiness = derive_readiness(all_issues)
    return AssessmentResult(
        readiness_status=readiness,
        issues=all_issues,
        rule_outcomes=rule_outcomes,
    )


def assess_single_asset(
    conn: sqlite3.Connection,
    asset_id: str,
    assessment_run_id: str,
    ruleset_data: Dict[str, Any],
    ruleset_version: str,
    ruleset_hash: str,
) -> Dict[str, Any]:
    """Full assessment pipeline for a single asset with input revalidation."""
    repo = AssessmentRepository(conn)

    # 1. Resolve lineage
    lineage, blocked_reason = resolve_asset_lineage(conn, asset_id)
    if not lineage:
        repo.insert_run_item(
            assessment_run_id, asset_id,
            decision="BLOCKED", execution_status="NOT_RUN",
            blocked_reason=blocked_reason,
        )
        return {"decision": "BLOCKED", "blocked_reason": blocked_reason}

    # 2. Compute signature
    input_signature = compute_input_signature(
        source_fingerprint=lineage.source_fingerprint,
        basic_analysis_run_id=lineage.basic_analysis_run_id,
        deep_analysis_run_id=lineage.deep_analysis_run_id,
        preview_id=lineage.preview_id,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        assessor_version=ASSESSOR_VERSION,
    )

    # 3. Check SKIP
    existing = repo.get_latest_successful_assessment(asset_id, ruleset_version)
    if existing and existing["assessment_input_signature"] == input_signature:
        repo.insert_run_item(
            assessment_run_id, asset_id,
            decision="SKIP", execution_status="NOT_RUN",
            input_signature=input_signature,
        )
        return {"decision": "SKIP", "input_signature": input_signature}

    # 4. Mark RUNNING
    conn.execute(
        "UPDATE assets SET assessment_status = 'RUNNING' WHERE asset_id = ?",
        (asset_id,),
    )
    conn.commit()

    # Insert preliminary run item
    repo.insert_run_item(
        assessment_run_id, asset_id,
        decision="NEEDS_ASSESSMENT", execution_status="NOT_RUN",
        input_signature=input_signature,
    )

    # 5. Evaluate all rules in memory
    try:
        result = evaluate_asset(conn, lineage, ruleset_data)
    except Exception as exc:
        logger.exception("Evaluator crashed for asset %s", asset_id)
        conn.execute(
            "UPDATE assets SET assessment_status = 'FAILED' WHERE asset_id = ?",
            (asset_id,),
        )
        conn.commit()
        repo.insert_run_item(
            assessment_run_id, asset_id,
            decision="NEEDS_ASSESSMENT", execution_status="FAILED",
            input_signature=input_signature,
            error_type=type(exc).__name__, error_message=str(exc)[:2000],
        )
        return {"decision": "NEEDS_ASSESSMENT", "execution_status": "FAILED", "error": str(exc)}

    # 6. Revalidate: re-resolve current lineage and check signature hasn't changed
    current_lineage, _ = resolve_asset_lineage(conn, asset_id)
    if current_lineage:
        current_sig = compute_input_signature(
            source_fingerprint=current_lineage.source_fingerprint,
            basic_analysis_run_id=current_lineage.basic_analysis_run_id,
            deep_analysis_run_id=current_lineage.deep_analysis_run_id,
            preview_id=current_lineage.preview_id,
            ruleset_version=ruleset_version,
            ruleset_hash=ruleset_hash,
            assessor_version=ASSESSOR_VERSION,
        )
        if current_sig != input_signature:
            logger.warning("Input changed during assessment for asset %s", asset_id)
            conn.execute(
                "UPDATE assets SET assessment_status = 'PENDING' WHERE asset_id = ?",
                (asset_id,),
            )
            conn.commit()
            repo.insert_run_item(
                assessment_run_id, asset_id,
                decision="NEEDS_ASSESSMENT", execution_status="INPUT_CHANGED",
                input_signature=input_signature,
            )
            return {"decision": "NEEDS_ASSESSMENT", "execution_status": "INPUT_CHANGED"}

    # 7. Persist atomically
    assessment_id = str(uuid.uuid4())
    blocking_reasons = [i.rule_code for i in result.issues if i.disposition != "NONE"]
    warnings = [i.rule_code for i in result.issues if i.severity == "WARNING"]

    lineage_dict = {
        "basic_analysis_run_id": lineage.basic_analysis_run_id,
        "deep_analysis_run_id": lineage.deep_analysis_run_id,
        "preview_id": lineage.preview_id,
        "render_run_id": lineage.render_run_id or "",
        "source_fingerprint": lineage.source_fingerprint,
        "source_file_size_bytes": lineage.source_file_size_bytes,
        "source_modified_time_ns": lineage.source_modified_time_ns,
        "analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "deep_analysis_schema_version": ANALYSIS_SCHEMA_VERSION,
        "render_schema_version": PREVIEW_SCHEMA_VERSION,
    }

    try:
        repo.persist_assessment(
            assessment_id=assessment_id,
            assessment_run_id=assessment_run_id,
            asset_id=asset_id,
            assessor_version=ASSESSOR_VERSION,
            ruleset_version=ruleset_version,
            ruleset_hash=ruleset_hash,
            lineage_dict=lineage_dict,
            input_signature=input_signature,
            readiness_status=result.readiness_status,
            issues=result.issues,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
        )
    except Exception as exc:
        logger.exception("Persistence failed for asset %s", asset_id)
        conn.execute(
            "UPDATE assets SET assessment_status = 'FAILED' WHERE asset_id = ?",
            (asset_id,),
        )
        conn.commit()
        repo.insert_run_item(
            assessment_run_id, asset_id,
            decision="NEEDS_ASSESSMENT", execution_status="FAILED",
            input_signature=input_signature,
            error_type=type(exc).__name__, error_message=str(exc)[:2000],
        )
        return {"decision": "NEEDS_ASSESSMENT", "execution_status": "FAILED", "error": str(exc)}

    return {
        "decision": "NEEDS_ASSESSMENT",
        "execution_status": "SUCCESS",
        "assessment_id": assessment_id,
        "readiness_status": result.readiness_status,
        "issues": result.issues,
        "rule_outcomes": result.rule_outcomes,
        "input_signature": input_signature,
    }


def run_batch_assessment(
    conn: sqlite3.Connection,
    source_root: Optional[str] = None,
    asset_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Run assessment across eligible assets."""
    repo = AssessmentRepository(conn)

    # Recover stale RUNNING
    recovered = repo.recover_stale_assessments()
    if recovered:
        logger.info("Recovered %d stale RUNNING assessments", recovered)

    # Load ruleset
    ruleset_data, ruleset_version, ruleset_hash = load_ruleset_with_hash()

    # Build query — scope to GLB/GLTF assets with complete lineage potential
    query = """SELECT asset_id, filename FROM assets
               WHERE is_present = 1
                 AND LOWER(extension) IN ('.glb', '.gltf')"""
    params = []
    if asset_id:
        query += " AND asset_id = ?"
        params.append(asset_id)
    elif source_root:
        query += " AND source_root = ?"
        params.append(source_root)

    conn.row_factory = sqlite3.Row
    assets = conn.execute(query, params).fetchall()

    # Create run
    run_id = str(uuid.uuid4())
    repo.create_assessment_run(
        assessment_run_id=run_id,
        assessor_version=ASSESSOR_VERSION,
        ruleset_version=ruleset_version,
        ruleset_hash=ruleset_hash,
        requested_asset_count=len(assets),
    )

    results = []
    for row in assets:
        aid = row["asset_id"]
        fname = row["filename"]
        logger.info("Assessing: %s (%s)", fname, aid)

        result = assess_single_asset(
            conn, aid, run_id,
            ruleset_data, ruleset_version, ruleset_hash,
        )
        result["filename"] = fname
        result["asset_id"] = aid
        results.append(result)

    # Finalize run
    repo.finalize_assessment_run(run_id)

    return {
        "assessment_run_id": run_id,
        "ruleset_version": ruleset_version,
        "ruleset_hash": ruleset_hash,
        "assessor_version": ASSESSOR_VERSION,
        "results": results,
    }
