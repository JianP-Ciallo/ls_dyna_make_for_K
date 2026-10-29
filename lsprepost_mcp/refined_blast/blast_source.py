"""Provider-evidence-bound blast source fragment compiler."""

from __future__ import annotations

from .fragments import KeywordFragment, ScenarioModuleContext, closed_mapping, require_literal, require_si_budgets, require_token


class BlastSourceCompiler:
    module_id = "blast_source"

    def compile(self, context: ScenarioModuleContext) -> KeywordFragment:
        raw = closed_mapping(
            context.input_for(self.module_id),
            frozenset({"schema_version", "unit_system", "source_declared_id", "source_space_id", "budgets"}),
            "blast_source",
        )
        require_literal(raw, "schema_version", "refined_blast.blast_source@1", "blast_source")
        source_id = require_token(raw["source_declared_id"], "blast_source.source_declared_id")
        source_space_id = require_token(raw["source_space_id"], "blast_source.source_space_id")
        if source_id not in context.provider_fragment.declared_ids:
            raise ValueError("blast source must reference a declared provider source")
        if source_id != context.provider_source_declared_id:
            raise ValueError("blast source must reference the provider source-space claim")
        if source_space_id != context.provider_source_space_id:
            raise ValueError("blast source space must match provider source space evidence")
        budgets = require_si_budgets(raw, "blast_source")
        return KeywordFragment(
            module_id=self.module_id,
            declared_ids=frozenset({f"blast_source:{source_id}"}),
            required_ids=frozenset({source_id}),
            estimates={"new_nodes": 0, "new_elements": 0, "budget_limits": budgets, "budget_checked_before_allocation": True},
            manifest={
                "source_id": source_id,
                "provider_id": context.provider_fragment.provider_id,
                "provider_declared_source_id": source_id,
                "source_space_id": source_space_id,
                "engineering_source_invented": False,
                "unit_system": "SI_m_s_kg_N_Pa",
            },
        )
