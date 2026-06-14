#!/usr/bin/env python3
"""Stage 0.5 — the feedback loop's bookkeeper.

Diffs this run's library snapshot against the previous run, and reconciles the
recommendation ledger:
  * titles the owner ADDED that we'd previously recommended  -> mark "acquired"
    (a strong "yes, more like this" signal) and surface them in the UI.
  * titles added that we didn't suggest                      -> taste we under-served.
  * standing picks the owner keeps skipping                  -> kept, gently down-weighted.

Writes:
  <workdir>/work/diff.json        # the added/removed/acquired delta (feeds Stage 7 + the site)
  <workdir>/work/exclusions.json  # owned + already-recommended titles + the next round number
  <workdir>/state/ledger.json     # updated in place (acquired marks)

Run AFTER scan_library.py and BEFORE generating this round's recommendations.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import plexlib as P  # noqa: E402
import config as C  # noqa: E402


def keyset(items):
    return {P.make_key(i["title"], i.get("year"), i["type"]): i for i in items}


def main():
    ap = argparse.ArgumentParser(description="Diff library snapshots and reconcile the ledger.")
    ap.add_argument("--config")
    ap.add_argument("--workdir")
    args = ap.parse_args()

    cfg = C.load(args.config)
    workdir = args.workdir or cfg["workdir"]
    state = os.path.join(workdir, "state")
    work = os.path.join(workdir, "work")

    cur = P.load_json(os.path.join(state, "library-latest.json"), [])
    prev = P.load_json(os.path.join(state, "library-previous.json"), [])
    ledger = P.load_json(os.path.join(state, "ledger.json"), [])
    last_run = P.load_json(os.path.join(state, "last-run.json"), {}) or {}

    if not cur:
        print("ERROR: no library-latest.json — run scan_library.py first.", file=sys.stderr)
        sys.exit(1)

    cur_keys, prev_keys = keyset(cur), keyset(prev)
    ledger_by_key = {P.make_key(e["title"], e.get("year"), e["type"]): e for e in ledger}
    first_run = not prev and not ledger

    added, removed, acquired_ids = [], [], []
    if not first_run:
        for k, it in cur_keys.items():
            if k not in prev_keys:
                was_rec = k in ledger_by_key
                if was_rec:
                    e = ledger_by_key[k]
                    if e.get("status") != "acquired":
                        e["status"] = "acquired"
                        e["acquiredAt"] = P.today()
                    acquired_ids.append(e["id"])
                added.append({"id": it["id"], "title": it["title"], "year": it.get("year", ""),
                              "type": it["type"], "wasRecommended": was_rec})
        for k, it in prev_keys.items():
            if k not in cur_keys:
                removed.append({"title": it["title"], "year": it.get("year", ""), "type": it["type"]})

    next_round = max([e.get("round", 0) for e in ledger] + [0]) + 1

    diff = {
        "previousRunAt": last_run.get("date", ""),
        "round": next_round,
        "isFirstRun": first_run,
        "added": added,
        "removed": removed,
        "acquiredFromRecs": acquired_ids,
        "counts": {"added": len(added), "removed": len(removed), "acquired": len(acquired_ids)},
    }
    exclusions = {
        "round": next_round,
        "ownedTitles": [{"title": i["title"], "year": i.get("year", ""), "type": i["type"]} for i in cur],
        "activeLedgerTitles": [{"title": e["title"], "year": e.get("year", ""), "type": e["type"]}
                               for e in ledger if e.get("status") == "active"],
    }

    P.write_json(os.path.join(work, "diff.json"), diff)
    P.write_json(os.path.join(work, "exclusions.json"), exclusions)
    P.write_json(os.path.join(state, "ledger.json"), ledger)

    if first_run:
        print(f"First run — no prior snapshot. Next round = {next_round}. {len(cur)} titles owned.")
    else:
        print(f"Diff: +{len(added)} added, -{len(removed)} removed, {len(acquired_ids)} of our picks acquired ✓")
    print(f"Next round = {next_round}. Wrote work/diff.json and work/exclusions.json.")


if __name__ == "__main__":
    main()
