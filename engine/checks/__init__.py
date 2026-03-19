"""
CHECK_PIPELINE: ordered list of (stage_name, check_function) tuples.

To add a new check:
  1. Create engine/checks/my_new_check.py with a function
     check_my_new_thing(supplier, ctx, data) -> CheckResult
  2. Import it here and add one entry to CHECK_PIPELINE below.
     The pipeline in phase1_filter.py iterates this list generically
     and never knows about specific check names.
"""
from __future__ import annotations

from typing import Callable

from engine.types import CheckResult, DataContext, RequestContext, SupplierRow

from .category_match       import check_category_match
from .region_match         import check_region_match
from .quantity_feasible    import check_quantity_feasible
from .not_restricted       import check_not_restricted
from .preferred_validation import check_preferred_validation
from .policy_compliant     import check_policy_compliant
from .pricing_available    import check_pricing_available
from .request_text_checks  import check_request_text

CheckFn = Callable[[SupplierRow, RequestContext, DataContext], CheckResult]

CHECK_PIPELINE: list[tuple[str, CheckFn]] = [
    ("category_match",       check_category_match),
    ("region_match",         check_region_match),
    ("quantity_feasible",    check_quantity_feasible),
    ("not_restricted",       check_not_restricted),
    ("preferred_validation", check_preferred_validation),
    ("policy_compliant",     check_policy_compliant),
    ("pricing_available",    check_pricing_available),
    ("request_text_checks",  check_request_text),
]

__all__ = ["CHECK_PIPELINE"]
