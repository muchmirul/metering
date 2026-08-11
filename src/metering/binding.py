"""Salted commitment for controller-private generated-instance truth."""

from __future__ import annotations

from typing import Any, Mapping

from .trace import canonical_json, sha256_hex

REFERENCE_COMMITMENT_ALGORITHM = "sha256"
_GENERATED_INSTANCE_KEYS = {
    "world_id",
    "world_version",
    "instance_id",
    "instance_version",
    "hidden_fault_id",
}


class BindingError(ValueError):
    """Raised when commitment input is not the exact v0 identity shape."""


def reference_commitment_payload(
    artifact_set_id: str,
    binding_nonce: str,
    generated_instance: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the unambiguous JSON value committed by the controller.

    The caller validates UUID syntax.  This helper enforces the complete
    generated-instance identity so adding or omitting a truth-bearing field
    cannot silently change what the commitment means.
    """

    if type(artifact_set_id) is not str or not artifact_set_id:
        raise BindingError("artifact_set_id must be a non-empty string")
    if type(binding_nonce) is not str or not binding_nonce:
        raise BindingError("binding_nonce must be a non-empty string")
    if type(generated_instance) is not dict or set(generated_instance) != (
        _GENERATED_INSTANCE_KEYS
    ):
        raise BindingError("generated_instance has an invalid commitment schema")
    identity: dict[str, str] = {}
    for key in sorted(_GENERATED_INSTANCE_KEYS):
        value = generated_instance[key]
        if type(value) is not str or not value:
            raise BindingError(f"generated_instance.{key} must be a string")
        identity[key] = value
    return {
        "artifact_set_id": artifact_set_id,
        "binding_nonce": binding_nonce,
        "generated_instance": identity,
    }


def compute_reference_commitment(
    artifact_set_id: str,
    binding_nonce: str,
    generated_instance: Mapping[str, Any],
) -> str:
    """Hash UTF-8 canonical JSON without an artifact newline."""

    payload = reference_commitment_payload(
        artifact_set_id, binding_nonce, generated_instance
    )
    return sha256_hex(canonical_json(payload).encode("utf-8"))
