"""A wooden-barrel-shaped prop: lathe body with a sine bulge, plus hoop
rings unioned on. Exercises the CSG vocabulary the crate does not:
add_lathe for the body, add_cylinder + boolean_union for the hoops.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

MINIMUM_BULGE_FACTOR = 1.0
# Hoops placed proportionally along the height (cooper convention:
# quarter hoops).
HOOP_POSITION_FRACTIONS = (0.2, 0.8)


@dataclass(frozen=True)
class BarrelParameters:
    """All dimensions in meters."""

    end_radius_m: float = 0.30
    height_m: float = 0.90
    bulge_factor: float = 1.18
    segment_count: int = 24
    ring_count: int = 8
    hoop_protrusion_m: float = 0.015
    hoop_height_m: float = 0.05
    name: str = "Barrel"

    def validate(self) -> None:
        if self.end_radius_m <= 0.0 or self.height_m <= 0.0:
            raise ValueError("Barrel radius and height must be positive.")
        if self.bulge_factor < MINIMUM_BULGE_FACTOR:
            raise ValueError(
                f"Bulge factor must be >= {MINIMUM_BULGE_FACTOR} "
                f"(1.0 = straight cylinder)."
            )
        if self.ring_count < 2:
            raise ValueError("Barrel needs at least two profile rings.")
        if self.hoop_height_m <= 0.0 or self.hoop_protrusion_m <= 0.0:
            raise ValueError("Hoop dimensions must be positive.")

    def radius_at_height(self, height_z_m: float) -> float:
        """Sine-bulged radius: end_radius at the ends, peak at mid-height."""
        height_fraction = height_z_m / self.height_m
        bulge_amount = (self.bulge_factor - 1.0) * math.sin(math.pi * height_fraction)
        return self.end_radius_m * (1.0 + bulge_amount)


class BarrelBuilder:
    def __init__(self, parameters: BarrelParameters) -> None:
        parameters.validate()
        self.parameters = parameters
        self.created_objects: list = []

    def build(self):
        from blended.ops import (
            add_cylinder,
            boolean_union,
            link_into_scene,
        )
        from blended.ops.lathe import add_lathe

        parameters = self.parameters
        profile = [
            (
                parameters.radius_at_height(
                    ring_index / parameters.ring_count * parameters.height_m
                ),
                ring_index / parameters.ring_count * parameters.height_m,
            )
            for ring_index in range(parameters.ring_count + 1)
        ]
        barrel_object = add_lathe(parameters.name, profile, parameters.segment_count)
        link_into_scene(barrel_object)
        self.created_objects.append(barrel_object)

        for hoop_index, height_fraction in enumerate(HOOP_POSITION_FRACTIONS):
            hoop_center_z_m = parameters.height_m * height_fraction
            hoop_radius_m = (
                parameters.radius_at_height(hoop_center_z_m)
                + parameters.hoop_protrusion_m
            )
            hoop_object = add_cylinder(
                f"{parameters.name}_hoop_{hoop_index}",
                radius_m=hoop_radius_m,
                height_m=parameters.hoop_height_m,
                segment_count=parameters.segment_count,
                location_m=(
                    0.0,
                    0.0,
                    hoop_center_z_m - parameters.hoop_height_m / 2.0,
                ),
            )
            link_into_scene(hoop_object)
            boolean_union(barrel_object, hoop_object)

        return barrel_object
