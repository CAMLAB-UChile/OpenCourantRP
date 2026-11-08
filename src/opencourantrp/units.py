"""Units the user declares for the model and the results (text only: nothing is converted)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

# (quantity key, label in the dialog, hint)
FIELDS = (
    ("length", "Dimensions", "e.g. mm"),
    ("time", "Times", "e.g. ms"),
    ("displacement", "Displacements", "e.g. mm"),
    ("velocity", "Velocities", "e.g. mm/s"),
    ("acceleration", "Accelerations", "e.g. mm/s2"),
    ("force", "Contact forces", "e.g. N"),
    ("stress", "Stresses", "e.g. MPa"),
    ("temperature", "Temperatures", "e.g. K"),
    ("mass", "Masses", "e.g. t"),
    ("energy", "Energies", "e.g. mJ"),
)


@dataclass(frozen=True)
class Units:
    length: str = ""
    time: str = ""
    displacement: str = ""
    velocity: str = ""
    acceleration: str = ""
    force: str = ""
    stress: str = ""
    temperature: str = ""
    mass: str = ""
    energy: str = ""

    def of(self, quantity: str | None) -> str:
        """Unit of a quantity key ("displacement", "stress", ...); empty when none or not declared.

        "energy/mass" (specific energies) and "mass/volume" (density) are built from the declared units and need both."""
        if quantity == "energy/mass":
            return f"{self.energy}/{self.mass}" if self.energy and self.mass else ""
        if quantity == "mass/volume":
            return f"{self.mass}/{self.length}^3" if self.mass and self.length else ""
        return getattr(self, quantity, "") if quantity else ""


def dumps(units: Units) -> str:
    return json.dumps(asdict(units))


def loads(text: str) -> Units:
    """Saved units; anything unreadable gives no units at all."""
    try:
        raw = json.loads(text)
        return Units(**{k: str(raw.get(k, "")).strip() for k in asdict(Units())})
    except (ValueError, TypeError, AttributeError):
        return Units()


def with_unit(text: str, unit: str) -> str:
    """`text` followed by the unit (nothing added when no unit is declared)."""
    return f"{text} {unit}" if unit else text
