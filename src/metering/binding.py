"""Salted commitment for controller-private generated-instance truth.

Before the policy runs, the controller hashes the selected fault together with
a fresh random nonce and publishes only that hash in the manifest.  After the
run, the reference artifact reveals both the fault and the nonce, and replay
recomputes the hash to confirm they match.

The nonce is what makes this useful.  Publishing a bare hash of one of eight
faults would be worthless, because a reader could hash all eight and see which
one matched.  With the nonce held back, the manifest commits to the truth
without disclosing it, so a hidden fault cannot be chosen or changed after the
policy has already acted.
"""

from __future__ import annotations

from typing import Any, Mapping

from .schema import SchemaError, StrictFields
from .trace import canonical_json, sha256_hex

REFERENCE_COMMITMENT_ALGORITHM = "sha256"

_GENERATED_INSTANCE_FIELDS = (
    "world_id",
    "world_version",
    "instance_id",
    "instance_version",
    "hidden_fault_id",
)


class BindingError(SchemaError):
    """Raised when commitment input is not the exact Metering identity shape."""


_check = StrictFields(BindingError)


def reference_commitment_payload(
    artifact_set_id: str,
    binding_nonce: str,
    generated_instance: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the unambiguous JSON value committed by the controller.

    The caller validates UUID syntax.  This helper requires the complete
    generated-instance identity, so adding or omitting a truth-bearing field
    cannot quietly change what the commitment covers.
    """

    _check.text(artifact_set_id, "artifact_set_id")
    _check.text(binding_nonce, "binding_nonce")
    fields = _check.exact_keys(
        generated_instance, _GENERATED_INSTANCE_FIELDS, "generated_instance"
    )
    return {
        "artifact_set_id": artifact_set_id,
        "binding_nonce": binding_nonce,
        "generated_instance": {
            key: _check.text(fields[key], f"generated_instance.{key}")
            for key in sorted(_GENERATED_INSTANCE_FIELDS)
        },
    }


def compute_reference_commitment(
    artifact_set_id: str,
    binding_nonce: str,
    generated_instance: Mapping[str, Any],
) -> str:
    """Hash UTF-8 canonical JSON without a trailing newline."""

    payload = reference_commitment_payload(
        artifact_set_id, binding_nonce, generated_instance
    )
    return sha256_hex(canonical_json(payload).encode("utf-8"))
