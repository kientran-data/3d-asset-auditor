"""Assessment repository — DB persistence for assessments, issues, and run items."""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from .models import StagedIssue


class AssessmentRepository:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self.conn.row_factory = sqlite3.Row

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------
    def get_latest_successful_assessment(
        self, asset_id: str, ruleset_version: str
    ) -> Optional[Dict[str, Any]]:
        row = self.conn.execute(
            """SELECT * FROM asset_assessments
               WHERE asset_id = ?
                 AND ruleset_version = ?
                 AND assessment_status = 'SUCCESS'
               ORDER BY id DESC LIMIT 1""",
            (asset_id, ruleset_version),
        ).fetchone()
        return dict(row) if row else None

    # -----------------------------------------------------------------------
    # Write — assessment run
    # -----------------------------------------------------------------------
    def create_assessment_run(
        self,
        assessment_run_id: str,
        assessor_version: str,
        ruleset_version: str,
        ruleset_hash: str,
        requested_asset_count: int,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT INTO assessment_runs
               (assessment_run_id, assessor_version, ruleset_version,
                ruleset_hash, started_at, status, requested_asset_count,
                assessed_asset_count, skipped_asset_count,
                blocked_asset_count, failed_asset_count)
               VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, 0, 0, 0, 0)""",
            (assessment_run_id, assessor_version, ruleset_version,
             ruleset_hash, now, requested_asset_count),
        )
        self.conn.commit()

    def finalize_assessment_run(self, assessment_run_id: str) -> None:
        """Derive final counters from assessment_run_items and update the run."""
        rows = self.conn.execute(
            """SELECT decision, execution_status FROM assessment_run_items
               WHERE assessment_run_id = ?""",
            (assessment_run_id,),
        ).fetchall()

        assessed = sum(1 for r in rows if r["execution_status"] == "SUCCESS")
        skipped = sum(1 for r in rows if r["decision"] == "SKIP")
        blocked = sum(1 for r in rows if r["decision"] == "BLOCKED")
        failed = sum(
            1 for r in rows
            if r["execution_status"] in ("FAILED", "INPUT_CHANGED")
        )

        if failed > 0:
            status = "COMPLETED_WITH_ERRORS"
        else:
            status = "SUCCESS"

        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """UPDATE assessment_runs
               SET status = ?, finished_at = ?,
                   assessed_asset_count = ?, skipped_asset_count = ?,
                   blocked_asset_count = ?, failed_asset_count = ?
               WHERE assessment_run_id = ?""",
            (status, now, assessed, skipped, blocked, failed, assessment_run_id),
        )
        self.conn.commit()

    # -----------------------------------------------------------------------
    # Write — run items (orchestration audit)
    # -----------------------------------------------------------------------
    def insert_run_item(
        self,
        assessment_run_id: str,
        asset_id: str,
        decision: str,
        execution_status: Optional[str] = None,
        blocked_reason: Optional[str] = None,
        assessment_id: Optional[str] = None,
        input_signature: Optional[str] = None,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            """INSERT OR REPLACE INTO assessment_run_items
               (assessment_run_id, asset_id, decision, execution_status,
                blocked_reason, assessment_id, assessment_input_signature,
                started_at, finished_at, error_type, error_message)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (assessment_run_id, asset_id, decision, execution_status,
             blocked_reason, assessment_id, input_signature,
             now, now, error_type, error_message),
        )
        self.conn.commit()

    # -----------------------------------------------------------------------
    # Write — single-asset assessment (atomic transaction)
    # -----------------------------------------------------------------------
    def persist_assessment(
        self,
        assessment_id: str,
        assessment_run_id: str,
        asset_id: str,
        assessor_version: str,
        ruleset_version: str,
        ruleset_hash: str,
        lineage_dict: Dict[str, Any],
        input_signature: str,
        readiness_status: str,
        issues: List[StagedIssue],
        blocking_reasons: List[str],
        warnings: List[str],
    ) -> None:
        """Persist assessment + issues in a single atomic transaction."""
        now = datetime.now(timezone.utc).isoformat()

        self.conn.execute("BEGIN")
        try:
            # Insert asset_assessments
            self.conn.execute(
                """INSERT INTO asset_assessments
                   (assessment_id, assessment_run_id, asset_id,
                    assessment_status, assessor_version,
                    ruleset_version, ruleset_hash,
                    basic_analysis_run_id, deep_analysis_run_id,
                    preview_id, render_run_id,
                    analysis_schema_version, deep_analysis_schema_version,
                    render_schema_version,
                    source_file_size_bytes, source_modified_time_ns,
                    source_fingerprint, assessment_input_signature,
                    geometry_score, material_score, texture_score,
                    preview_score, naming_score, packaging_score,
                    overall_score, readiness_status,
                    blocking_reasons_json, warnings_json,
                    assessment_details_json, assessed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                           ?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    assessment_id, assessment_run_id, asset_id,
                    "SUCCESS", assessor_version,
                    ruleset_version, ruleset_hash,
                    lineage_dict["basic_analysis_run_id"],
                    lineage_dict["deep_analysis_run_id"],
                    lineage_dict["preview_id"],
                    lineage_dict.get("render_run_id", ""),
                    lineage_dict.get("analysis_schema_version", ""),
                    lineage_dict.get("deep_analysis_schema_version", ""),
                    lineage_dict.get("render_schema_version", ""),
                    lineage_dict["source_file_size_bytes"],
                    lineage_dict["source_modified_time_ns"],
                    lineage_dict["source_fingerprint"],
                    input_signature,
                    None, None, None, None, None, None, None,  # All scores NULL
                    readiness_status,
                    json.dumps(blocking_reasons),
                    json.dumps(warnings),
                    "{}",
                    now,
                ),
            )

            # Insert assessment_issues
            for issue in issues:
                self.conn.execute(
                    """INSERT INTO assessment_issues
                       (assessment_id, asset_id, rule_code, severity,
                        disposition, category, message,
                        observed_value_json, expected_value_json,
                        details_json, subject_type, subject_key)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        assessment_id, asset_id, issue.rule_code,
                        issue.severity, issue.disposition, issue.category,
                        issue.message,
                        json.dumps(issue.observed_value) if issue.observed_value else None,
                        json.dumps(issue.expected_value) if issue.expected_value else None,
                        None,
                        issue.subject_type, issue.subject_key,
                    ),
                )

            # Update run item
            self.conn.execute(
                """UPDATE assessment_run_items
                   SET execution_status = 'SUCCESS',
                       assessment_id = ?,
                       finished_at = ?
                   WHERE assessment_run_id = ? AND asset_id = ?""",
                (assessment_id, now, assessment_run_id, asset_id),
            )

            # Update pipeline status
            self.conn.execute(
                "UPDATE assets SET assessment_status = 'SUCCESS' WHERE asset_id = ?",
                (asset_id,),
            )

            self.conn.execute("COMMIT")
        except Exception:
            self.conn.execute("ROLLBACK")
            raise

    # -----------------------------------------------------------------------
    # Stale RUNNING recovery
    # -----------------------------------------------------------------------
    def recover_stale_assessments(self) -> int:
        """Reset assets stuck in RUNNING assessment_status back to PENDING."""
        cursor = self.conn.execute(
            "UPDATE assets SET assessment_status = 'PENDING' WHERE assessment_status = 'RUNNING'"
        )
        self.conn.commit()
        return cursor.rowcount
