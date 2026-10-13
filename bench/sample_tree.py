#!/usr/bin/env python3
"""Inclusive sample counts from a macOS `sample` report.

    bench/sample_tree.py <sample.txt> [--threads] [--pattern REGEX ...]

For each pattern, sums the samples of the outermost frames whose symbol
matches (so recursion and nested matches are not double counted), per thread
and in total. Without patterns, prints the busiest frames at a few depths of
each thread. Idle frames (cvwait, semwait, ...) are reported separately.
"""

import argparse
import re
import sys
from collections import defaultdict

LINE = re.compile(r"^(?P<prefix>[\s+!:|]*)(?P<count>\d+) (?P<sym>.+?)(?:\s+\(in [^)]*\))?(?: \+ [\d,.]+)?(?:\s+\[[^\]]*\])?\s*$")
THREAD = re.compile(r"^\s*(?P<count>\d+) Thread_(?P<id>\d+)(?P<rest>.*)$")
IDLE = re.compile(r"__psynch_cvwait|__semwait_signal|__workq_kernreturn|mach_msg2_trap|kevent|__ulock_wait")


def parse(path):
    """Yield (thread, depth, count, symbol) for every call-graph frame."""
    in_graph = False
    thread = None
    with open(path, errors="replace") as f:
        for line in f:
            if line.startswith("Call graph:"):
                in_graph = True
                continue
            if not in_graph:
                continue
            if line.startswith("Total number in stack") or line.startswith("Sort by top of stack"):
                break
            m = THREAD.match(line)
            if m:
                thread = f"Thread_{m['id']}{m['rest'].strip()[:40]}"
                yield thread, 0, int(m["count"]), "<thread>"
                continue
            m = LINE.match(line.rstrip("\n"))
            if m and thread:
                yield thread, len(m["prefix"]), int(m["count"]), m["sym"].strip()


def inclusive(path, patterns):
    regs = [(p, re.compile(p)) for p in patterns]
    totals = defaultdict(lambda: defaultdict(int))
    thread_total = defaultdict(int)
    thread_idle = defaultdict(int)
    stack = []  # (depth, matched-pattern-set)
    for thread, depth, count, sym in parse(path):
        if sym == "<thread>":
            stack = []
            thread_total[thread] = count
            continue
        while stack and stack[-1][0] >= depth:
            stack.pop()
        active = set().union(*(s[1] for s in stack)) if stack else set()
        matched = set()
        for p, r in regs:
            if r.search(sym):
                matched.add(p)
                if p not in active:
                    totals[p][thread] += count
        if IDLE.search(sym) and "idle" not in active:
            thread_idle[thread] += count
            matched.add("idle")
        stack.append((depth, active | matched))
    return totals, thread_total, thread_idle


def self_time(path, thread_regex, under=None):
    """Self samples per symbol for threads matching thread_regex, optionally
    only counting frames below an ancestor matching `under`."""
    tre = re.compile(thread_regex)
    ure = re.compile(under) if under else None
    selfs = defaultdict(int)
    stack = []  # [depth, sym, count, child_sum, under_active]
    keep = False

    def flush(entry):
        depth, sym, count, child_sum, active = entry
        if active:
            selfs[sym] += count - child_sum

    for thread, depth, count, sym in parse(path):
        if sym == "<thread>":
            while stack:
                flush(stack.pop())
            keep = bool(tre.search(thread))
            continue
        if not keep:
            continue
        while stack and stack[-1][0] >= depth:
            flush(stack.pop())
        parent_active = stack[-1][4] if stack else False
        active = parent_active or (ure is None) or bool(ure.search(sym))
        if stack:
            stack[-1][3] += count
        stack.append([depth, sym, count, 0, active])
    while stack:
        flush(stack.pop())
    return selfs


def callers(path, thread_regex, target, depth=6):
    """Samples of the outermost frames matching `target`, grouped by their
    nearest `depth` ancestors."""
    tre = re.compile(thread_regex)
    target_re = re.compile(target)
    chains = defaultdict(int)
    stack = []  # (depth, sym)
    keep = False
    for thread, d, count, sym in parse(path):
        if sym == "<thread>":
            stack = []
            keep = bool(tre.search(thread))
            continue
        if not keep:
            continue
        while stack and stack[-1][0] >= d:
            stack.pop()
        if target_re.search(sym) and not any(target_re.search(s) for _, s in stack):
            chain = [short(s) for _, s in stack[-depth:]] + [short(sym)]
            chains[" > ".join(chain)] += count
        stack.append((d, sym))
    return chains


def short(sym):
    sym = re.sub(r"\(.*", "", sym)
    sym = re.sub(r"<[^<>]*(<[^<>]*>[^<>]*)*>", "<>", sym)
    return sym[-60:]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sample")
    ap.add_argument("--pattern", "-p", action="append", default=[])
    ap.add_argument("--threads", action="store_true", help="per-thread breakdown")
    ap.add_argument("--self", dest="self_thread", metavar="THREAD_REGEX",
                    help="print top self-time symbols for matching threads")
    ap.add_argument("--under", help="with --self: only frames below this symbol regex")
    ap.add_argument("--callers", metavar="SYMBOL_REGEX",
                    help="with --self: group matching frames by their ancestors")
    ap.add_argument("--depth", type=int, default=6)
    ap.add_argument("--top", type=int, default=30)
    args = ap.parse_args()

    if args.callers:
        chains = callers(args.sample, args.self_thread or ".", args.callers, args.depth)
        print(f"samples: {sum(chains.values())}")
        for chain, c in sorted(chains.items(), key=lambda x: -x[1])[:args.top]:
            print(f"{c:>8}  {chain}")
        return 0

    if args.self_thread:
        selfs = self_time(args.sample, args.self_thread, args.under)
        total = sum(selfs.values())
        print(f"self samples: {total}")
        for sym, c in sorted(selfs.items(), key=lambda x: -x[1])[:args.top]:
            print(f"{c:>8}  {sym[:150]}")
        return 0

    totals, thread_total, thread_idle = inclusive(args.sample, args.pattern)
    all_total = sum(thread_total.values())
    all_idle = sum(thread_idle.values())
    print(f"threads: {len(thread_total)}  samples: {all_total}  idle: {all_idle}  "
          f"busy: {all_total - all_idle}")
    if args.threads:
        for t in sorted(thread_total, key=lambda t: -(thread_total[t] - thread_idle[t])):
            busy = thread_total[t] - thread_idle[t]
            if busy:
                print(f"  {busy:>8} busy / {thread_total[t]:>8}  {t}")
    for p in args.pattern:
        s = sum(totals[p].values())
        print(f"{s:>9}  {p}")
        if args.threads:
            for t, c in sorted(totals[p].items(), key=lambda x: -x[1])[:4]:
                print(f"{'':>11}{c:>8}  {t}")


if __name__ == "__main__":
    sys.exit(main())
