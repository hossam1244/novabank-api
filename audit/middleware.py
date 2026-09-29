"""Audit middleware — records every mutating API call.

Domain services record semantically rich events (`payment.settled`); this
middleware guarantees a floor of coverage: any POST/PUT/PATCH/DELETE under
/api/ leaves a trace even if a view forgets to audit. Only status codes and
metadata like method/path/duration are stored — never request bodies, which
may contain credentials or beneficiary data.
"""

import re
import time

from audit.services import record_audit

MUTATING_METHODS = ("POST", "PUT", "PATCH", "DELETE")

ORG_IN_PATH = re.compile(r"^/api/v1/orgs/([0-9a-f-]{36})/")


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start = time.monotonic()
        response = self.get_response(request)
        if request.path.startswith("/api/") and request.method in MUTATING_METHODS:
            organization = None
            match = ORG_IN_PATH.match(request.path)
            if match:
                from accounts.models import Organization

                organization = Organization.objects.filter(pk=match[1]).first()
            record_audit(
                request,
                organization=organization,
                action="api.request",
                metadata={
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round((time.monotonic() - start) * 1000, 1),
                },
            )
        return response
