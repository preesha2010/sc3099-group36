"""Fixed-cardinality, process-local metrics. No user-controlled metric labels."""

from collections import defaultdict
from contextlib import contextmanager
from threading import Lock
from time import perf_counter
import os
from functools import wraps

ROUTES = {"/", "/health", "/ready", "/metrics", "/face/enroll", "/face/verify",
          "/face/match", "/liveness/check", "/risk/assess", "/risk/policy"}
BUCKETS = (.01, .05, .1, .25, .5, 1, 2, 5, 10, 30)


def rss_bytes():
    """Current resident memory, not Python-only allocations or peak RSS."""
    try:
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            class Counters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetCurrentProcess.restype = wintypes.HANDLE
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
            counter = Counters()
            counter.cb = ctypes.sizeof(counter)
            if psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(counter), counter.cb):
                return counter.WorkingSetSize
        else:
            from pathlib import Path
            return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError, AttributeError):
        pass
    return None


class Metrics:
    def __init__(self):
        self.lock = Lock()
        self.requests = defaultdict(int)
        self.timings = {}
        self.active = 0
        self.pending = 0
        self.rejected = 0
        self.trace_export_failures = 0

    def trace_failed(self):
        with self.lock:
            self.trace_export_failures += 1

    def observe(self, stage, seconds):
        with self.lock:
            item = self.timings.setdefault(stage, [0, 0., [0] * len(BUCKETS)])
            item[0] += 1
            item[1] += seconds
            for index, bound in enumerate(BUCKETS):
                item[2][index] += seconds <= bound

    @contextmanager
    def stage(self, name):
        from app.telemetry import trace_stage
        start = perf_counter()
        try:
            with trace_stage(name):
                yield
        finally:
            self.observe(name, perf_counter() - start)

    def request(self, path, status, seconds):
        route = path if path in ROUTES else "other"
        with self.lock:
            self.requests[(route, str(status))] += 1
        if route not in {"/metrics", "/health", "/ready"}:
            self.observe("http_" + route.replace("/", "_") if route != "other" else "http_other", seconds)

    def render(self):
        lines = ["# TYPE module3_http_requests_total counter"]
        with self.lock:
            for (route, status), count in sorted(self.requests.items()):
                lines.append(f'module3_http_requests_total{{route="{route}",status="{status}"}} {count}')
            lines += ["# TYPE module3_stage_seconds histogram"]
            for stage, (count, total, buckets) in sorted(self.timings.items()):
                for limit, value in zip(BUCKETS, buckets):
                    lines.append(f'module3_stage_seconds_bucket{{stage="{stage}",le="{limit}"}} {value}')
                lines += [f'module3_stage_seconds_bucket{{stage="{stage}",le="+Inf"}} {count}',
                          f'module3_stage_seconds_count{{stage="{stage}"}} {count}',
                          f'module3_stage_seconds_sum{{stage="{stage}"}} {total:.9f}']
            for name, value in (("active", self.active), ("pending", self.pending)):
                lines += [f"# TYPE module3_inference_{name} gauge", f"module3_inference_{name} {value}"]
            lines += ["# TYPE module3_overload_rejections_total counter",
                      f"module3_overload_rejections_total {self.rejected}"]
            lines += ["# TYPE module3_trace_export_failures_total counter",
                      f"module3_trace_export_failures_total {self.trace_export_failures}"]
        memory = rss_bytes()
        if memory is not None:
            lines += ["# TYPE module3_process_resident_bytes gauge", f"module3_process_resident_bytes {memory}"]
        return "\n".join(lines) + "\n"


metrics = Metrics()


def timed(stage):
    def decorate(function):
        @wraps(function)
        def measured(*args, **kwargs):
            with metrics.stage(stage):
                return function(*args, **kwargs)
        return measured
    return decorate
