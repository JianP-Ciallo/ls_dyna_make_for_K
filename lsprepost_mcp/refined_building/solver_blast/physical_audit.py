"""Physical selection audit for mixed Solid/Shell/Beam buildings."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import AuditFinding, PhysicalInterfaceRecord, PhysicalMemberRecord


_OPAQUE_ENVELOPE_ROLES = frozenset(
    {
        "opaque_facade",
        "opaque_envelope",
        "masonry_wall",
        "precast_wall",
    }
)


def audit_physical_members(
    members: Iterable[PhysicalMemberRecord],
) -> tuple[AuditFinding, ...]:
    """Return deterministic hard findings for unjustified element-family choices."""

    findings: list[AuditFinding] = []
    seen_roles: set[str] = set()
    for member in members:
        if not isinstance(member, PhysicalMemberRecord):
            raise TypeError("members must contain PhysicalMemberRecord values")
        if member.role in seen_roles:
            findings.append(
                AuditFinding(
                    "duplicate_member_role",
                    member.role,
                    "member role is declared more than once",
                )
            )
        seen_roles.add(member.role)

        if member.role in _OPAQUE_ENVELOPE_ROLES and member.element_family != "Solid":
            findings.append(
                AuditFinding(
                    "opaque_envelope_requires_solid",
                    member.role,
                    "opaque facade/envelope must have a meshed solid volume",
                )
            )
        if member.element_family == "Beam":
            length, section_a, section_b = member.dimensions_m
            if member.orientation_vector is None:
                findings.append(
                    AuditFinding(
                        "beam_requires_orientation",
                        member.role,
                        "beam requires an explicit section orientation",
                    )
                )
            if (
                length / max(section_a, section_b) < 10.0
                and "reviewed non-slender beam exception" not in member.selection_basis
            ):
                findings.append(
                    AuditFinding(
                        "beam_not_slender",
                        member.role,
                        "beam slenderness is below the reviewed minimum of 10",
                    )
                )
        elif member.element_family == "Shell":
            length, width, thickness = member.dimensions_m
            if min(length, width) / thickness < 10.0:
                findings.append(
                    AuditFinding(
                        "shell_not_thin",
                        member.role,
                        "shell in-plane-to-thickness ratio is below 10",
                    )
                )
    return tuple(sorted(findings, key=lambda row: (row.member_role, row.finding_id)))


def audit_physical_connections(
    members: Iterable[PhysicalMemberRecord],
    interfaces: Iterable[PhysicalInterfaceRecord],
) -> tuple[AuditFinding, ...]:
    """Audit that every member points to measured, owned interface evidence."""

    member_rows = tuple(members)
    interface_rows = tuple(interfaces)
    findings = list(audit_physical_members(member_rows))
    by_id: dict[str, PhysicalInterfaceRecord] = {}
    for interface in interface_rows:
        if interface.interface_id in by_id:
            findings.append(
                AuditFinding(
                    "duplicate_interface_id",
                    interface.interface_id,
                    "physical interface identifier is declared more than once",
                )
            )
        by_id[interface.interface_id] = interface
        if (
            interface.shared_node_count == 0
            and interface.positive_contact_area_m2 == 0.0
            and interface.positive_contact_length_m == 0.0
            and interface.connection_type != "artifact_constraint"
        ):
            findings.append(
                AuditFinding(
                    "interface_without_geometric_evidence",
                    interface.interface_id,
                    "physical interface has no shared-node, contact-area, or artifact evidence",
                )
            )

    for member in member_rows:
        for interface_id in member.connection_ids:
            interface = by_id.get(interface_id)
            if interface is None:
                findings.append(
                    AuditFinding(
                        "missing_interface_record",
                        member.role,
                        f"connection {interface_id!r} has no physical interface record",
                    )
                )
                continue
            if member.role not in (*interface.source_roles, *interface.target_roles):
                findings.append(
                    AuditFinding(
                        "interface_does_not_own_member",
                        member.role,
                        f"connection {interface_id!r} does not reference the member role",
                    )
                )
    return tuple(sorted(findings, key=lambda row: (row.member_role, row.finding_id)))
