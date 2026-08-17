"""Governed sports identity-bridge consumers and registries."""

from .consumer import (
    IdentityBridgeValidationError,
    MlbFd1IdentityBridgeAdapter,
    SportsIdentityBridgeV1Consumer,
    ValidatedIdentityBridge,
)
from .mlb_adapter import MLBFD1IdentityAdapter
from .registry import SportsIdentityBridgeRegistry

__all__ = [
    "IdentityBridgeValidationError",
    "MLBFD1IdentityAdapter",
    "MlbFd1IdentityBridgeAdapter",
    "SportsIdentityBridgeRegistry",
    "SportsIdentityBridgeV1Consumer",
    "ValidatedIdentityBridge",
]
