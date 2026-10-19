"""One owner per local database; do not run uvicorn workers>1 on a shared network drive."""

import asyncio
import os
from pathlib import Path


class WorkerLease:
    def __init__(self, database):
        self.path = Path(str(database) + ".literature.lock")
        self.fd = None

    def acquire(self):
        self.fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        if os.fstat(self.fd).st_size == 0:
            os.write(self.fd, b"0")
        try:
            if os.name == "nt":
                import msvcrt

                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            os.close(self.fd)
            self.fd = None
            return False

    def close(self):
        if self.fd is not None:
            if os.name == "nt":
                import msvcrt

                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            os.close(self.fd)
            self.fd = None


async def run_worker(service):
    lease = WorkerLease(service.library.database)
    if not lease.acquire():
        return
    try:
        service.store.recover()
        while True:
            step = asyncio.create_task(asyncio.to_thread(service.run_next))
            try:
                worked = await asyncio.shield(step)
            except asyncio.CancelledError:
                # Retain ownership until the bounded model request/checkpoint finishes.
                await step
                raise
            if not worked:
                await asyncio.sleep(1)
    finally:
        lease.close()
