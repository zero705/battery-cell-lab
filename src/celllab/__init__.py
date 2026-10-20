"""An equivalent circuit model of the LG 18650HG2 lithium-ion cell."""

from celllab.ecm import CellModel, Simulation, simulate_current, simulate_power
from celllab.model_file import load_model

__all__ = ["CellModel", "Simulation", "load_model", "simulate_current", "simulate_power"]
__version__ = "0.1.0"
