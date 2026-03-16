"""Grant collector package."""

from .nih import NIHCollector
from .eu_portal import EUPortalCollector
from .grants_gov import GrantsGovCollector
from .carb_x import CarbXCollector
from .right_foundation import RightFoundationCollector
from .gates_gc import GatesGCCollector
from .pasteur_network import PasteurNetworkCollector
from .google_org import GoogleOrgCollector

__all__ = [
    "NIHCollector",
    "EUPortalCollector",
    "GrantsGovCollector",
    "CarbXCollector",
    "RightFoundationCollector",
    "GatesGCCollector",
    "PasteurNetworkCollector",
    "GoogleOrgCollector",
]
