"""Versioned, serializable evaluator calibration profiles."""

import hashlib
import json
import math
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing_extensions import Any, Literal, Self, TypeGuard

PROFILE_SCHEMA_VERSION = 1
CALIBRATION_ALGORITHM_VERSION = 1
_COMPATIBILITY_COMPONENTS = ("version", "dataset", "evaluators", "step_sizes")

WeightingMethod = Literal["equal", "reliability", "inverse_step", "inverse_sqrt_step"]
WEIGHTING_METHODS: tuple[WeightingMethod, ...] = (
    "equal",
    "reliability",
    "inverse_step",
    "inverse_sqrt_step",
)

BootstrapSummary = dict[str, float | int | None]


class ProfileCompatibility(str, Enum):
    """Compatibility between a profile and an evaluation configuration."""

    COMPATIBLE = "compatible"
    STALE = "stale"
    INCOMPATIBLE = "incompatible"


class BootstrapDiagnostics(BaseModel):
    """Bootstrap settings and uncertainty summaries saved with a profile."""

    model_config = ConfigDict(allow_inf_nan=False, extra="forbid", frozen=True)

    replicates: int = Field(ge=2)
    seed: int
    reliability_intervals: dict[str, BootstrapSummary]
    candidate_weight_intervals: dict[WeightingMethod, dict[str, BootstrapSummary]]
    composite_score_intervals: dict[WeightingMethod, BootstrapSummary]


class CalibrationProfile(BaseModel):
    """Durable record of one fitted evaluator calibration."""

    model_config = ConfigDict(
        allow_inf_nan=False,
        extra="forbid",
        frozen=True,
    )

    schema_version: int = PROFILE_SCHEMA_VERSION
    algorithm_version: int = Field(default=CALIBRATION_ALGORITHM_VERSION, ge=0)
    profile_id: str
    weighting_method: WeightingMethod
    weights: dict[str, float]
    step_sizes: dict[str, float]
    variance_components: dict[str, dict[str, float]]
    reliabilities: dict[str, float]
    case_count: int = Field(ge=2)
    agent_runs: int = Field(ge=2)
    judge_replays: int = Field(ge=2)
    calibration_context: dict[str, Any] | None
    report_structure_fingerprint: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    bootstrap: BootstrapDiagnostics | None = None

    @model_validator(mode="after")
    def _validate_profile(self) -> Self:
        if self.schema_version != PROFILE_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported calibration profile schema version: {self.schema_version}; "
                f"expected {PROFILE_SCHEMA_VERSION}"
            )

        evaluator_names = set(self.step_sizes)
        if not evaluator_names:
            raise ValueError("calibration profile must contain at least one evaluator")
        if any(not math.isfinite(value) or value <= 0.0 for value in self.step_sizes.values()):
            raise ValueError("profile step sizes must be finite and greater than zero")
        if set(self.weights) != evaluator_names:
            raise ValueError("weights evaluator names must match step_sizes")
        if set(self.variance_components) != evaluator_names:
            raise ValueError("variance_components evaluator names must match step_sizes")
        if set(self.reliabilities) != evaluator_names:
            raise ValueError("reliabilities evaluator names must match step_sizes")

        if any(not math.isfinite(value) or value < 0.0 for value in self.weights.values()):
            raise ValueError("profile weights must be finite and non-negative")
        if not math.isclose(sum(self.weights.values()), 1.0, abs_tol=1e-12):
            raise ValueError("profile weights must sum to 1")

        expected_id = self.calculate_profile_id(
            self.model_dump(mode="json", exclude={"profile_id"}),
        )
        if self.profile_id != expected_id:
            raise ValueError("calibration profile ID does not match its contents")
        return self

    @classmethod
    def create(cls, **data: Any) -> Self:
        """Create a profile and derive its deterministic content ID."""
        profile_data = dict(data)
        bootstrap = profile_data.get("bootstrap")
        if isinstance(bootstrap, dict):
            profile_data["bootstrap"] = BootstrapDiagnostics.model_validate(bootstrap)

        draft = cls.model_construct(profile_id="", **profile_data)
        payload = draft.model_dump(mode="json", exclude={"profile_id"})
        return cls(profile_id=cls.calculate_profile_id(payload), **payload)

    @staticmethod
    def calculate_profile_id(payload: dict[str, Any]) -> str:
        """Calculate a deterministic SHA-256 identifier for profile contents."""
        serialized = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def compatibility_with(
        self,
        calibration_context: dict[str, Any] | None,
    ) -> ProfileCompatibility:
        """Classify this profile against an evaluation configuration."""
        runtime_compatibility = self.runtime_compatibility
        if runtime_compatibility != ProfileCompatibility.COMPATIBLE:
            return runtime_compatibility
        if not _has_compatibility_components(calibration_context):
            return ProfileCompatibility.INCOMPATIBLE

        assert self.calibration_context is not None
        if any(
            calibration_context[component] != self.calibration_context[component]
            for component in _COMPATIBILITY_COMPONENTS
        ):
            return ProfileCompatibility.INCOMPATIBLE
        return ProfileCompatibility.COMPATIBLE

    @property
    def runtime_compatibility(self) -> ProfileCompatibility:
        """Classify whether this runtime can safely restore the profile."""
        if not _has_compatibility_components(self.calibration_context) and self.report_structure_fingerprint is None:
            return ProfileCompatibility.INCOMPATIBLE

        if self.algorithm_version < CALIBRATION_ALGORITHM_VERSION:
            return ProfileCompatibility.STALE
        if self.algorithm_version > CALIBRATION_ALGORITHM_VERSION:
            return ProfileCompatibility.INCOMPATIBLE
        return ProfileCompatibility.COMPATIBLE

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible profile dictionary."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Load and validate a profile dictionary."""
        return cls.model_validate(data)

    def to_file(self, path: str) -> None:
        """Write the profile to a deterministic JSON file."""
        file_path = _json_path(path, require_extension=False)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as file:
            json.dump(
                self.to_dict(),
                file,
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
                allow_nan=False,
            )
            file.write("\n")

    @classmethod
    def from_file(cls, path: str) -> Self:
        """Load and validate a profile from a JSON file."""
        file_path = _json_path(path, require_extension=True)
        with open(file_path, encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict):
            raise ValueError("calibration profile JSON must contain an object")
        return cls.from_dict(data)


def _json_path(path: str, *, require_extension: bool) -> Path:
    """Normalize and validate a profile JSON path."""
    file_path = Path(path)
    if file_path.suffix and file_path.suffix != ".json":
        raise ValueError(f"only .json calibration profiles are supported, got: {path}")
    if require_extension and file_path.suffix != ".json":
        raise ValueError(f"calibration profile path must use a .json extension, got: {path}")
    return file_path if file_path.suffix else file_path.with_suffix(".json")


def _has_compatibility_components(
    calibration_context: dict[str, Any] | None,
) -> TypeGuard[dict[str, Any]]:
    """Return whether a context contains every required fingerprint."""
    return calibration_context is not None and all(
        isinstance(calibration_context.get(component), str) and bool(calibration_context[component])
        for component in _COMPATIBILITY_COMPONENTS
    )
