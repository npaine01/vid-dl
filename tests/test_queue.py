"""Tests for the serial job queue."""
import os
import sys
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import jobs


def recorder(order, delay=0):
    """A runner that records execution order."""
    def run(job):
        if delay:
            time.sleep(delay)
        order.append(job.id)
        job.status = "done"
    return run


class TestSerialExecution(unittest.TestCase):
    def test_runs_queued_jobs_one_at_a_time_in_order(self):
        order = []
        queue = jobs.JobQueue(runner=recorder(order)).start()
        added = [queue.add(jobs.Job(url=f"u{n}")) for n in range(4)]
        self.assertTrue(queue.wait_idle())
        self.assertEqual(order, [job.id for job in added])

    def test_never_runs_two_jobs_at_once(self):
        concurrent, peak = [0], [0]
        lock = threading.Lock()

        def run(job):
            with lock:
                concurrent[0] += 1
                peak[0] = max(peak[0], concurrent[0])
            time.sleep(0.02)
            with lock:
                concurrent[0] -= 1
            job.status = "done"

        queue = jobs.JobQueue(runner=run).start()
        for n in range(5):
            queue.add(jobs.Job(url=f"u{n}"))
        self.assertTrue(queue.wait_idle())
        self.assertEqual(peak[0], 1)

    def test_a_failing_job_does_not_stall_the_queue(self):
        order = []

        def run(job):
            if job.url == "boom":
                raise RuntimeError("job blew up")
            order.append(job.url)
            job.status = "done"

        queue = jobs.JobQueue(runner=run).start()
        queue.add(jobs.Job(url="boom"))
        queue.add(jobs.Job(url="after"))
        self.assertTrue(queue.wait_idle())
        self.assertEqual(order, ["after"])

    def test_records_the_failure_on_the_job(self):
        def run(job):
            raise RuntimeError("job blew up")

        queue = jobs.JobQueue(runner=run).start()
        job = queue.add(jobs.Job(url="boom"))
        self.assertTrue(queue.wait_idle())
        self.assertEqual(job.status, "error")
        self.assertIn("blew up", job.error)


class TestStopping(unittest.TestCase):
    def test_stop_leaves_the_running_job_alone_and_drops_the_rest(self):
        started = threading.Event()
        release = threading.Event()

        def run(job):
            started.set()
            release.wait(2)
            job.status = "done"

        queue = jobs.JobQueue(runner=run).start()
        running = queue.add(jobs.Job(url="running"))
        pending = [queue.add(jobs.Job(url=f"p{n}")) for n in range(3)]

        self.assertTrue(started.wait(2))
        dropped = queue.stop_after_current()
        release.set()
        self.assertTrue(queue.wait_idle())

        self.assertEqual(running.status, "done")
        self.assertEqual([job.id for job in dropped], [job.id for job in pending])
        for job in pending:
            self.assertEqual(job.status, "cancelled")

    def test_cancelling_a_pending_job_removes_it_from_the_queue(self):
        order = []
        release = threading.Event()

        def run(job):
            release.wait(2)
            order.append(job.url)
            job.status = "done"

        queue = jobs.JobQueue(runner=run).start()
        queue.add(jobs.Job(url="first"))
        doomed = queue.add(jobs.Job(url="doomed"))
        queue.add(jobs.Job(url="last"))

        self.assertTrue(queue.cancel(doomed.id))
        release.set()
        self.assertTrue(queue.wait_idle())
        self.assertEqual(order, ["first", "last"])
        self.assertEqual(doomed.status, "cancelled")

    def test_cancelling_the_running_job_terminates_its_process(self):
        started = threading.Event()
        terminated = threading.Event()

        class FakeProcess:
            def terminate(self):
                terminated.set()

        def run(job):
            job.process = FakeProcess()
            started.set()
            terminated.wait(2)
            job.status = "cancelled" if job.cancelled else "done"

        queue = jobs.JobQueue(runner=run).start()
        job = queue.add(jobs.Job(url="running"))
        self.assertTrue(started.wait(2))
        self.assertTrue(queue.cancel(job.id))
        self.assertTrue(queue.wait_idle())
        self.assertTrue(terminated.is_set())
        self.assertEqual(job.status, "cancelled")

    def test_cancelling_an_unknown_job_reports_failure(self):
        queue = jobs.JobQueue(runner=recorder([])).start()
        self.assertFalse(queue.cancel("nosuchjob"))


class TestSnapshot(unittest.TestCase):
    def test_lists_every_job_in_the_order_added(self):
        queue = jobs.JobQueue(runner=recorder([])).start()
        added = [queue.add(jobs.Job(url=f"u{n}")) for n in range(3)]
        self.assertTrue(queue.wait_idle())
        self.assertEqual([entry["id"] for entry in queue.snapshot()],
                         [job.id for job in added])

    def test_reports_whether_the_queue_is_stopping(self):
        queue = jobs.JobQueue(runner=recorder([])).start()
        self.assertFalse(queue.state()["stopping"])
        queue.stop_after_current()
        self.assertTrue(queue.state()["stopping"])
