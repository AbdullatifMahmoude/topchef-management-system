"""Read-only HTTP load probe for a deployed Top Chef test environment."""

import argparse
import asyncio
import math
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class LoadResult:
    requests: int
    errors: int
    elapsed: float
    p50_ms: float
    p95_ms: float
    p99_ms: float

    @property
    def requests_per_second(self) -> float:
        return self.requests / self.elapsed if self.elapsed else 0.0


def percentile(values: list[float], percentage: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percentage * len(ordered)) - 1)
    return ordered[max(index, 0)]


async def run_load(url: str, requests: int, concurrency: int, timeout: float) -> LoadResult:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors = 0
    limits = httpx.Limits(max_connections=concurrency, max_keepalive_connections=concurrency)

    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        async def execute() -> None:
            nonlocal errors
            async with semaphore:
                started = time.perf_counter()
                try:
                    response = await client.get(url)
                    if response.status_code >= 400:
                        errors += 1
                except httpx.HTTPError:
                    errors += 1
                finally:
                    latencies.append((time.perf_counter() - started) * 1000)

        started = time.perf_counter()
        await asyncio.gather(*(execute() for _ in range(requests)))
        elapsed = time.perf_counter() - started

    return LoadResult(
        requests=requests,
        errors=errors,
        elapsed=elapsed,
        p50_ms=percentile(latencies, 0.50),
        p95_ms=percentile(latencies, 0.95),
        p99_ms=percentile(latencies, 0.99),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a read-only load probe against /health or another safe GET endpoint.")
    parser.add_argument("url", help="Full URL; use a staging environment, not production.")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=25)
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    if args.requests < 1 or args.concurrency < 1 or args.concurrency > 500:
        parser.error("requests must be positive and concurrency must be between 1 and 500")
    result = asyncio.run(run_load(args.url, args.requests, args.concurrency, args.timeout))
    print(f"requests={result.requests} errors={result.errors} elapsed={result.elapsed:.2f}s")
    print(f"throughput={result.requests_per_second:.1f} req/s p50={result.p50_ms:.1f}ms p95={result.p95_ms:.1f}ms p99={result.p99_ms:.1f}ms")
    if result.errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
