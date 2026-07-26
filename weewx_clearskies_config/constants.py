"""Module-level constants shared by more than one router.

Both ``wizard/routes.py`` and ``admin/routes.py`` deliberately avoid importing
from each other, so that neither router module has an import-time dependency
on the other (see the ``_()`` helper duplicated in each).  A value needed by
both used to be copied into both files, which satisfied that rule at the cost
of two literals for one fact (C-63).  This module is the third place both may
import from: it imports nothing from either router, so the rule holds and the
value exists once.

Only genuinely shared, router-independent constants belong here.  Anything
owned by one surface stays in that surface's module.
"""

from __future__ import annotations

#: Address the marine companion service is reached at when it runs on the same
#: host as the API.  Filled in by the "same host" checkbox on both the wizard's
#: providers step and the admin Marine Service section (T7.2), and documented
#: as the same-host example in API-MANUAL §19.2.
MARINE_SAME_HOST_URL = "https://localhost:8780"
