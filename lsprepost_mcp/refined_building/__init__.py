"""Phase 18C refined-building kernel.

This package owns building-space and structural-system semantics.  It is
deliberately independent from scene generators so the same building artifact
can be used by more than one analysis workflow.
"""

from .contracts import default_building_definition, normalize_building_definition
from .compiler import compile_refined_building
from .asset_compiler import DetailedBuildingPackage, compile_detailed_building_asset
from .asset_resources import (
    DetailedBuildingAssetDescriptor,
    get_detailed_building_asset,
    list_detailed_building_assets,
)
from .systems import get_structural_system, list_structural_systems

__all__ = [
    "DetailedBuildingAssetDescriptor",
    "DetailedBuildingPackage",
    "default_building_definition",
    "compile_detailed_building_asset",
    "compile_refined_building",
    "get_detailed_building_asset",
    "get_structural_system",
    "list_detailed_building_assets",
    "list_structural_systems",
    "normalize_building_definition",
]
