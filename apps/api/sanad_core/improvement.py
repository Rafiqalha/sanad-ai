"""Controlled, privacy-conscious improvement tracking for SANAD.AI.

This module intentionally does *not* train a model, rewrite routing rules, or
apply production changes.  It provides two bounded facilities:

* aggregate sanitized failure-pattern observations using a fixed taxonomy;
* move a versioned candidate through test and regression gates before a human
  approval marker can be recorded.

Approved candidates still require a separate manual release.  There is no
automatic production-update path in this framework.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
import re
from threading import RLock
from typing import Any, Mapping
import unicodedata
from uuid import uuid4


class ImprovementCategory(str, Enum):
    FAILED_QUERY = "failed_query"
    UNKNOWN_MISROUTE = "unknown_misroute"
    RETRIEVAL_FAILURE = "retrieval_failure"
    NO_RESULT_PATTERN = "no_result_pattern"
    INDONESIAN_PARAPHRASE = "indonesian_paraphrase"
    WRONG_ATTRIBUTION = "wrong_attribution"
    RANKING_FAILURE = "ranking_failure"


class ImprovementStage(str, Enum):
    CANDIDATE = "CANDIDATE"
    TESTED = "TESTED"
    REGRESSION_VALIDATED = "REGRESSION_VALIDATED"
    APPROVED = "APPROVED"


class ImprovementError(RuntimeError):
    """Base class for controlled-improvement failures."""


class WorkflowTransitionError(ImprovementError):
    """Raised when a candidate tries to skip or repeat a required gate."""


class ImprovementValidationError(ImprovementError):
    """Raised when tests or regression validation did not pass."""


class AutomaticUpdateProhibitedError(ImprovementError):
    """Raised for attempts to self-train or auto-apply a candidate."""


_MAX_PATTERN_LENGTH = 600
_MAX_SUMMARY_LENGTH = 1_000
_MAX_PROPOSAL_LENGTH = 4_000
_MAX_METADATA_ITEMS = 20

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_URL = re.compile(r"(?i)\bhttps?://[^\s<>'\"]+")
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b("
    r"api[_-]?key|access[_-]?token|refresh[_-]?token|token|secret|password|"
    r"passwd|authorization|client[_-]?secret"
    r")\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
_KNOWN_CREDENTIAL = re.compile(
    r"(?i)\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[0-9A-Z]{16})\b"
)
_LONG_OPAQUE_TOKEN = re.compile(r"\b[A-Za-z0-9_-]{24,}\b")
_PHONE_LIKE = re.compile(r"(?<!\w)(?:\+?\d[\d ().-]{7,}\d)(?!\w)")
_SENSITIVE_METADATA_KEY = re.compile(
    r"(?i)(api.?key|authorization|cookie|credential|password|secret|session|token)"
)
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def sanitize_observation_text(value: str, *, max_length: int = _MAX_PATTERN_LENGTH) -> str:
    """Remove common credentials/PII and bound telemetry text.

    The returned value is suitable for pattern aggregation, not for replaying
    a user's original request.  The raw value is never retained by this
    module.
    """

    if not isinstance(value, str):
        raise TypeError("observation text must be a string")

    cleaned = unicodedata.normalize("NFKC", value)
    cleaned = _CONTROL_CHARS.sub(" ", cleaned)
    cleaned = _BEARER.sub("Bearer [REDACTED]", cleaned)
    cleaned = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", cleaned
    )
    cleaned = _KNOWN_CREDENTIAL.sub("[REDACTED]", cleaned)
    cleaned = _EMAIL.sub("[EMAIL]", cleaned)
    cleaned = _URL.sub("[URL]", cleaned)
    cleaned = _PHONE_LIKE.sub("[PHONE]", cleaned)
    cleaned = _LONG_OPAQUE_TOKEN.sub("[REDACTED]", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > max_length:
        cleaned = f"{cleaned[: max_length - 1].rstrip()}…"
    return cleaned


def _coerce_category(value: ImprovementCategory | str) -> ImprovementCategory:
    if isinstance(value, ImprovementCategory):
        return value
    normalized = value.strip()
    try:
        return ImprovementCategory(normalized.casefold())
    except ValueError:
        try:
            return ImprovementCategory[normalized.upper()]
        except KeyError as exc:
            raise ValueError(f"unsupported improvement category: {value!r}") from exc


def _sanitize_metadata(metadata: Mapping[str, Any] | None) -> dict[str, str]:
    safe: dict[str, str] = {}
    if not metadata:
        return safe

    for raw_key, raw_value in list(metadata.items())[:_MAX_METADATA_ITEMS]:
        key = sanitize_observation_text(str(raw_key), max_length=80)
        if not key:
            continue
        if _SENSITIVE_METADATA_KEY.search(key):
            safe[key] = "[REDACTED]"
            continue
        if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
            safe[key] = sanitize_observation_text(str(raw_value), max_length=240)
        else:
            # Nested objects often contain headers, request bodies, or provider
            # payloads.  Deliberately do not serialize them into telemetry.
            safe[key] = "[OMITTED_COMPLEX_VALUE]"
    return safe


@dataclass(frozen=True, slots=True)
class ImprovementObservation:
    category: ImprovementCategory
    sanitized_pattern: str
    fingerprint: str
    count: int
    first_seen_at: datetime
    last_seen_at: datetime
    metadata: Mapping[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category.value,
            "sanitized_pattern": self.sanitized_pattern,
            "fingerprint": self.fingerprint,
            "count": self.count,
            "first_seen_at": self.first_seen_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
            "metadata": dict(self.metadata),
        }


class ImprovementTracker:
    """In-memory, aggregate-only recorder for sanitized improvement signals."""

    def __init__(self) -> None:
        self._observations: dict[str, ImprovementObservation] = {}
        self._lock = RLock()

    def record(
        self,
        category: ImprovementCategory | str,
        pattern: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ImprovementObservation:
        safe_category = _coerce_category(category)
        safe_pattern = sanitize_observation_text(pattern)
        if not safe_pattern:
            raise ValueError("sanitized observation pattern must not be empty")
        safe_metadata = _sanitize_metadata(metadata)
        material = json.dumps(
            {
                "category": safe_category.value,
                "pattern": safe_pattern.casefold(),
                "metadata": safe_metadata,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        fingerprint = hashlib.sha256(material.encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)

        with self._lock:
            current = self._observations.get(fingerprint)
            if current is None:
                observation = ImprovementObservation(
                    category=safe_category,
                    sanitized_pattern=safe_pattern,
                    fingerprint=fingerprint,
                    count=1,
                    first_seen_at=now,
                    last_seen_at=now,
                    metadata=dict(safe_metadata),
                )
            else:
                observation = replace(
                    current,
                    count=current.count + 1,
                    last_seen_at=now,
                )
            self._observations[fingerprint] = observation
            return observation

    def observations(self) -> tuple[ImprovementObservation, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._observations.values(),
                    key=lambda item: (item.first_seen_at, item.fingerprint),
                )
            )

    def export_sanitized(self) -> list[dict[str, Any]]:
        return [item.to_dict() for item in self.observations()]


@dataclass(frozen=True, slots=True)
class ImprovementCandidate:
    candidate_id: str
    version: str
    category: ImprovementCategory
    summary: str
    proposed_change: str
    stage: ImprovementStage
    created_at: datetime
    updated_at: datetime
    test_reference: str | None = None
    regression_reference: str | None = None
    approval_reference: str | None = None
    approved_by: str | None = None
    requires_manual_release: bool = True


class ImprovementWorkflow:
    """Versioned candidate -> test -> regression -> approval state machine."""

    automatic_production_updates = False
    automatic_self_training = False

    def __init__(self) -> None:
        self._candidates: dict[str, ImprovementCandidate] = {}
        self._versions: set[str] = set()
        self._lock = RLock()

    def create_candidate(
        self,
        *,
        version: str,
        category: ImprovementCategory | str,
        summary: str,
        proposed_change: str,
    ) -> ImprovementCandidate:
        if not _VERSION.fullmatch(version):
            raise ValueError("version must be a short explicit version identifier")
        safe_summary = sanitize_observation_text(
            summary, max_length=_MAX_SUMMARY_LENGTH
        )
        safe_proposal = sanitize_observation_text(
            proposed_change, max_length=_MAX_PROPOSAL_LENGTH
        )
        if not safe_summary or not safe_proposal:
            raise ValueError("summary and proposed_change must not be empty")

        now = datetime.now(timezone.utc)
        with self._lock:
            if version in self._versions:
                raise ValueError(f"candidate version already exists: {version}")
            candidate = ImprovementCandidate(
                candidate_id=uuid4().hex,
                version=version,
                category=_coerce_category(category),
                summary=safe_summary,
                proposed_change=safe_proposal,
                stage=ImprovementStage.CANDIDATE,
                created_at=now,
                updated_at=now,
            )
            self._candidates[candidate.candidate_id] = candidate
            self._versions.add(version)
            return candidate

    def get(self, candidate_id: str) -> ImprovementCandidate:
        with self._lock:
            try:
                return self._candidates[candidate_id]
            except KeyError as exc:
                raise KeyError(f"unknown improvement candidate: {candidate_id}") from exc

    def candidates(self) -> tuple[ImprovementCandidate, ...]:
        with self._lock:
            return tuple(
                sorted(
                    self._candidates.values(),
                    key=lambda item: (item.created_at, item.candidate_id),
                )
            )

    def mark_tested(
        self,
        candidate_id: str,
        *,
        passed: bool,
        test_reference: str,
    ) -> ImprovementCandidate:
        if not passed:
            raise ImprovementValidationError(
                "candidate tests did not pass; stage was not advanced"
            )
        return self._transition(
            candidate_id,
            required=ImprovementStage.CANDIDATE,
            target=ImprovementStage.TESTED,
            test_reference=self._required_safe_reference(test_reference),
        )

    def mark_regression_validated(
        self,
        candidate_id: str,
        *,
        passed: bool,
        regression_reference: str,
    ) -> ImprovementCandidate:
        if not passed:
            raise ImprovementValidationError(
                "regression validation did not pass; stage was not advanced"
            )
        return self._transition(
            candidate_id,
            required=ImprovementStage.TESTED,
            target=ImprovementStage.REGRESSION_VALIDATED,
            regression_reference=self._required_safe_reference(
                regression_reference
            ),
        )

    def approve(
        self,
        candidate_id: str,
        *,
        approved_by: str,
        approval_reference: str,
    ) -> ImprovementCandidate:
        safe_reviewer = self._required_safe_reference(approved_by)
        safe_reference = self._required_safe_reference(approval_reference)
        return self._transition(
            candidate_id,
            required=ImprovementStage.REGRESSION_VALIDATED,
            target=ImprovementStage.APPROVED,
            approved_by=safe_reviewer,
            approval_reference=safe_reference,
        )

    def _required_safe_reference(self, value: str) -> str:
        safe = sanitize_observation_text(value, max_length=300)
        if not safe:
            raise ValueError("workflow reference must not be empty")
        return safe

    def _transition(
        self,
        candidate_id: str,
        *,
        required: ImprovementStage,
        target: ImprovementStage,
        **changes: str,
    ) -> ImprovementCandidate:
        with self._lock:
            candidate = self.get(candidate_id)
            if candidate.stage != required:
                raise WorkflowTransitionError(
                    f"cannot move {candidate.stage.value} to {target.value}; "
                    f"required stage is {required.value}"
                )
            updated = replace(
                candidate,
                stage=target,
                updated_at=datetime.now(timezone.utc),
                **changes,
            )
            self._candidates[candidate_id] = updated
            return updated

    def apply_to_production(self, candidate_id: str) -> None:
        self.get(candidate_id)
        raise AutomaticUpdateProhibitedError(
            "Automatic production updates are prohibited; use the manual release process."
        )

    def self_train(self, *_args: Any, **_kwargs: Any) -> None:
        raise AutomaticUpdateProhibitedError(
            "Automatic self-training is prohibited by the SANAD.AI improvement policy."
        )


class ControlledImprovementFramework:
    """Convenience container keeping telemetry and workflow boundaries clear."""

    automatic_production_updates = False
    automatic_self_training = False

    def __init__(self) -> None:
        self.tracker = ImprovementTracker()
        self.workflow = ImprovementWorkflow()

    def record(
        self,
        category: ImprovementCategory | str,
        pattern: str,
        *,
        metadata: Mapping[str, Any] | None = None,
    ) -> ImprovementObservation:
        return self.tracker.record(category, pattern, metadata=metadata)


__all__ = [
    "AutomaticUpdateProhibitedError",
    "ControlledImprovementFramework",
    "ImprovementCandidate",
    "ImprovementCategory",
    "ImprovementError",
    "ImprovementObservation",
    "ImprovementStage",
    "ImprovementTracker",
    "ImprovementValidationError",
    "ImprovementWorkflow",
    "WorkflowTransitionError",
    "sanitize_observation_text",
]
