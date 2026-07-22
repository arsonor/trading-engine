"""Pre-market scanner cron entrypoint (Phase 0 stub).

Wired into `render.yaml` so the cron job exists and can be scheduled/monitored
before the real scanner lands in Phase 2. Logs one line and exits 0.

Timezone note: Render cron runs in UTC. The real scanner (Phase 2) must convert
to America/New_York explicitly and gate work on the ET clock so DST transitions
do not shift the scan by an hour twice a year.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("premarket_scan.stub")


def main() -> int:
    now_utc = datetime.now(timezone.utc)
    log.info(
        "premarket-scan stub invoked at %s UTC — no scanner logic implemented yet (Phase 2)",
        now_utc.isoformat(timespec="seconds"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
