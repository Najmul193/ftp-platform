"""Start the stored-results warm-up after a data change.

After an upload or a deletion every stored dashboard result belongs to the old
data version. Rebuilding them in a separate process, straight after the change,
means the first person to open a page is served a stored result instead of
waiting for the heavy analytics to run.

A separate process rather than a thread: it keeps the web worker free, and its
progress goes to the same log as the server's. Disable with
WARM_CACHE_AFTER_UPLOAD=0.
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[2]


def spawn_warm_cache(batch_ref: str, expect: str) -> None:
    """Launch `app.cli.warm_cache` for the state after `batch_ref` changed.

    `expect` is "present" after an upload and "absent" after a deletion; the
    warm-up waits until that is visible, so it never pre-computes the data
    version the request is about to replace.
    """
    if os.environ.get("WARM_CACHE_AFTER_UPLOAD", "1") != "1":
        return
    try:
        subprocess.Popen(
            [sys.executable, "-m", "app.cli.warm_cache",
             "--after-batch", batch_ref, "--expect", expect],
            cwd=BACKEND_DIR, start_new_session=True,
        )
    except Exception:  # noqa: BLE001 - a missed warm-up only costs the first view
        log.warning("could not start the stored-results warm-up", exc_info=True)
