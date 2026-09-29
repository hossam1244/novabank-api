"""Scoped throttle for payment creation.

DRF's `ScopedRateThrottle` resolves rates through a class-level
`THROTTLE_RATES` snapshot, which does not always reflect later settings
overrides (tests, runtime reconfiguration). This subclass reads the current
settings on every request — same configuration, always live.
"""

from rest_framework.settings import api_settings
from rest_framework.throttling import ScopedRateThrottle


class PaymentCreateThrottle(ScopedRateThrottle):
    scope = "payments"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES[self.scope]
