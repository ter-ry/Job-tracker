"""Keep the legacy multi-workflow regression suite explicit.

Production defaults to SWE-only. Existing tests which exercise preserved ECE
behavior run with the reversible flag enabled unless a test overrides it.
"""

import os


os.environ.setdefault("JOB_TRACKER_ECE_ENABLED", "1")
