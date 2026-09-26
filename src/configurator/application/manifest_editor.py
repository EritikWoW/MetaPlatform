from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from src.configurator.manifest_schema import ManifestObject

from .service import ConfiguratorService


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """A single validation issue for the manifest editor.

    Attributes
    - field: logical field name (e.g. "title", "name", "payload.picture.asset_key")
    - message: human-readable description suitable for UI
    """

    field: str
    message: str


@dataclass(slots=True)
class ManifestEditorState:
    """In-memory editing state for a single manifest object."""

    guid: str = ""
    original: dict[str, Any] | None = None
    current: dict[str, Any] | None = None
    issues: list[ValidationIssue] | None = None

    @property
    def is_dirty(self) -> bool:
        """Return True if current state differs from the original snapshot."""

        return (self.original or {}) != (self.current or {})


class ManifestEditorService:
    """Manifest editor service (Qt-free).

    Responsibilities
    - load an object into an editable state (snapshot)
    - apply changes via ConfiguratorService using a single manifest rebuild
    - run lightweight validation suitable for UI feedback

    Notes
    - This layer does not try to be a full schema validator; it only enforces
      essential invariants for safe editing.
    """

    def __init__(self, service: ConfiguratorService) -> None:
        self._service = service
        self._state = ManifestEditorState()

    @property
    def state(self) -> ManifestEditorState:
        """Current editor state (mutable dataclass)."""

        return self._state

    def load(self, obj: ManifestObject) -> ManifestEditorState:
        """Load a manifest object into editor state."""

        payload = obj.payload if isinstance(obj.payload, dict) else {}
        snap: dict[str, Any] = {
            "guid": str(obj.guid),
            "type": str(obj.type),
            "name": str(obj.name),
            "title": str(obj.title),
            "payload": dict(payload),
            "kind": str(obj.kind),
            "parent_guid": str(obj.parent_guid or ""),
        }

        self._state = ManifestEditorState(
            guid=str(obj.guid),
            original=dict(snap),
            current=dict(snap),
            issues=[],
        )
        return self._state

    def set_field(self, field: str, value: Any) -> None:
        """Set a top-level field in the current snapshot.

        Supported fields:
        - type, name, title, payload

        For nested payload updates use set_payload_value().
        """

        if not self._state.current:
            return

        if field not in {"type", "name", "title", "payload"}:
            raise ValueError(f"Unsupported field: {field}")

        if field == "payload":
            self._state.current["payload"] = dict(value or {})
            return

        self._state.current[field] = value

    def set_payload_value(self, path: str, value: Any) -> None:
        """Set a nested payload value by dot-separated path.

        Example:
            set_payload_value("picture.asset_key", "pictures/a.svg")
        """

        if not self._state.current:
            return

        payload = self._state.current.get("payload")
        if not isinstance(payload, dict):
            payload = {}
            self._state.current["payload"] = payload

        keys = [k for k in str(path or "").split(".") if k]
        if not keys:
            return

        cur: dict[str, Any] = payload
        for k in keys[:-1]:
            nxt = cur.get(k)
            if not isinstance(nxt, dict):
                nxt = {}
                cur[k] = nxt
            cur = nxt
        cur[keys[-1]] = value

    def validate(self) -> list[ValidationIssue]:
        """Run minimal validation and store issues into state."""

        issues: list[ValidationIssue] = []
        cur = self._state.current or {}

        title = str(cur.get("title") or "").strip()
        if not title:
            issues.append(ValidationIssue("title", "Title must not be empty."))

        name = str(cur.get("name") or "").strip()
        if not name:
            issues.append(ValidationIssue("name", "Name must not be empty."))

        payload = cur.get("payload")
        if payload is not None and not isinstance(payload, Mapping):
            issues.append(ValidationIssue("payload", "Payload must be an object/dict."))

        self._state.issues = issues
        return issues

    def revert(self) -> ManifestEditorState:
        """Discard all changes and restore the original snapshot."""

        if self._state.original is None:
            return self._state
        self._state.current = dict(self._state.original)
        self._state.issues = []
        return self._state

    def apply(self) -> None:
        """Persist current changes into mpdb manifest.

        Raises RuntimeError if validation fails.
        """

        if not self._state.current:
            return

        issues = self.validate()
        if issues:
            msgs = ", ".join(f"{i.field}: {i.message}" for i in issues)
            raise RuntimeError(f"Manifest validation failed: {msgs}")

        guid = str(self._state.current.get("guid") or "").strip()
        if not guid:
            return

        self._service.update_object_fields(
            guid,
            obj_type=str(self._state.current.get("type") or ""),
            name=str(self._state.current.get("name") or ""),
            title=str(self._state.current.get("title") or ""),
            payload=dict(self._state.current.get("payload") or {}),
        )

        # Refresh snapshots (so further edits compare to the saved state)
        self._state.original = dict(self._state.current)
        self._state.issues = []
