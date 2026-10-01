from __future__ import annotations

import json

import pytest

from sanad_core.improvement import (
    AutomaticUpdateProhibitedError,
    ControlledImprovementFramework,
    ImprovementCategory,
    ImprovementStage,
    ImprovementTracker,
    ImprovementValidationError,
    ImprovementWorkflow,
    WorkflowTransitionError,
    sanitize_observation_text,
)


def test_fixed_taxonomy_covers_requested_safe_tracking_categories():
    assert {category.value for category in ImprovementCategory} == {
        "failed_query",
        "unknown_misroute",
        "retrieval_failure",
        "no_result_pattern",
        "indonesian_paraphrase",
        "wrong_attribution",
        "ranking_failure",
    }


def test_tracker_sanitizes_secrets_and_pii_without_retaining_raw_payloads():
    tracker = ImprovementTracker()
    secret = "super-secret-provider-key"
    opaque = "abc123abc123abc123abc123abc123"
    observation = tracker.record(
        ImprovementCategory.RETRIEVAL_FAILURE,
        (
            "api_key="
            f"{secret} user=test@example.com URL https://example.test/?token={opaque} "
            "Bearer bearer-value-123"
        ),
        metadata={
            "provider": "fixture",
            "authorization": secret,
            "request_payload": {"nested_secret": secret},
        },
    )

    serialized = json.dumps(tracker.export_sanitized(), ensure_ascii=False)
    assert secret not in serialized
    assert opaque not in serialized
    assert "test@example.com" not in serialized
    assert "https://example.test" not in serialized
    assert "[REDACTED]" in serialized
    assert "[EMAIL]" in serialized
    assert "[URL]" in serialized
    assert observation.metadata["authorization"] == "[REDACTED]"
    assert observation.metadata["request_payload"] == "[OMITTED_COMPLEX_VALUE]"


def test_duplicate_sanitized_observations_are_aggregated_not_replayed():
    tracker = ImprovementTracker()
    first = tracker.record(
        "unknown_misroute",
        "Pertanyaan sejarah dirutekan ke UNKNOWN",
        metadata={"actual_domain": "UNKNOWN"},
    )
    second = tracker.record(
        ImprovementCategory.UNKNOWN_MISROUTE,
        "Pertanyaan sejarah dirutekan ke UNKNOWN",
        metadata={"actual_domain": "UNKNOWN"},
    )

    assert first.fingerprint == second.fingerprint
    assert second.count == 2
    assert len(tracker.observations()) == 1


def test_sanitizer_is_bounded_and_rejects_non_string_input():
    assert len(sanitize_observation_text("x" * 2_000, max_length=100)) <= 100
    with pytest.raises(TypeError):
        sanitize_observation_text(123)  # type: ignore[arg-type]


def _candidate(workflow: ImprovementWorkflow):
    return workflow.create_candidate(
        version="v2.1.0-candidate.1",
        category=ImprovementCategory.RANKING_FAILURE,
        summary="Perbaiki urutan kandidat yang relevan.",
        proposed_change="Ubah bobot setelah evaluasi fixture terversi.",
    )


def test_workflow_enforces_candidate_test_regression_approval_order():
    workflow = ImprovementWorkflow()
    candidate = _candidate(workflow)

    assert candidate.stage == ImprovementStage.CANDIDATE
    assert candidate.requires_manual_release is True
    assert workflow.automatic_production_updates is False
    assert workflow.automatic_self_training is False

    with pytest.raises(WorkflowTransitionError):
        workflow.mark_regression_validated(
            candidate.candidate_id,
            passed=True,
            regression_reference="regression:premature",
        )
    with pytest.raises(WorkflowTransitionError):
        workflow.approve(
            candidate.candidate_id,
            approved_by="reviewer",
            approval_reference="approval:premature",
        )

    tested = workflow.mark_tested(
        candidate.candidate_id,
        passed=True,
        test_reference="pytest:test_candidate_v2_1",
    )
    assert tested.stage == ImprovementStage.TESTED

    regression = workflow.mark_regression_validated(
        candidate.candidate_id,
        passed=True,
        regression_reference="pytest:full_regression_2026_09_27",
    )
    assert regression.stage == ImprovementStage.REGRESSION_VALIDATED

    approved = workflow.approve(
        candidate.candidate_id,
        approved_by="human-reviewer",
        approval_reference="review:SANAD-v2.1",
    )
    assert approved.stage == ImprovementStage.APPROVED
    assert approved.requires_manual_release is True


def test_failed_validation_never_advances_and_auto_updates_are_prohibited():
    workflow = ImprovementWorkflow()
    candidate = _candidate(workflow)

    with pytest.raises(ImprovementValidationError, match="did not pass"):
        workflow.mark_tested(
            candidate.candidate_id,
            passed=False,
            test_reference="pytest:failed",
        )
    assert workflow.get(candidate.candidate_id).stage == ImprovementStage.CANDIDATE

    with pytest.raises(AutomaticUpdateProhibitedError, match="manual release"):
        workflow.apply_to_production(candidate.candidate_id)
    with pytest.raises(AutomaticUpdateProhibitedError, match="self-training"):
        workflow.self_train(["raw user data"])


def test_versions_are_unique_and_candidate_fields_are_sanitized():
    workflow = ImprovementWorkflow()
    candidate = workflow.create_candidate(
        version="v2.2.0-candidate.1",
        category="wrong_attribution",
        summary="Review api_key=do-not-store-this",
        proposed_change="Gunakan fixture; kontak reviewer@example.com",
    )

    assert "do-not-store-this" not in candidate.summary
    assert "reviewer@example.com" not in candidate.proposed_change
    with pytest.raises(ValueError, match="already exists"):
        workflow.create_candidate(
            version=candidate.version,
            category="failed_query",
            summary="Duplikat",
            proposed_change="Tidak boleh dibuat.",
        )


def test_framework_keeps_observation_and_release_workflow_separate():
    framework = ControlledImprovementFramework()
    observation = framework.record(
        ImprovementCategory.NO_RESULT_PATTERN,
        "Parafrasa Indonesia yang tidak menghasilkan kandidat",
    )

    assert observation.count == 1
    assert framework.tracker.observations() == (observation,)
    assert framework.workflow.candidates() == ()
    assert framework.automatic_production_updates is False
    assert framework.automatic_self_training is False
