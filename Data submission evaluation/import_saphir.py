"""Bring SAPHIR data-system files from the Z: drive into Incoming - Upload.

For every day of the campaign calendar (``campaign.py``), the day folder
``Z:\\IEK8-SAPHIR\\data\\YYYY\\MM\\DD`` is listed once and each .nc file is:

* copied unmodified (native name) if its product is in
  ``settings.SAPHIR_IMPORT_PRODUCTS`` (chamber state, meteo, LIF, kOH);
* merged with the other photolysis-frequency files of that day into ONE
  submission-format CSV, YYYY-MM-DD.JVALUES.FZJ.csv (``jvalues.py``);
* skipped if listed in ``settings.SAPHIR_IGNORED_PRODUCTS``;
* otherwise reported as NEW ON Z, so a newly processed instrument is noticed.

Re-running only touches what changed: a copy is replaced when size or time of
the Z: file differ, a J-value CSV is rebuilt when any of its sources changed.
Files already archived (Archive - Download/_Originals) count as present, so an
updated file on Z: comes back through Incoming and becomes a new archive version.

    python import_saphir.py --dry-run        # show what would happen
    python import_saphir.py                  # do it
    python import_saphir.py --inventory      # table of products per day on Z:
    python import_saphir.py --days 2026-07-07 2026-07-09
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import shutil
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import archive
import campaign
import jvalues
import settings as S


@dataclass
class ImportResult:
    copied: list[str] = field(default_factory=list)
    built: list[str] = field(default_factory=list)
    current: int = 0
    missing: list[str] = field(default_factory=list)
    new_products: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    inventory: dict[dt.date, list[str]] = field(default_factory=dict)


def day_dir(day: dt.date) -> Path:
    return S.SAPHIR_Z / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}"


def product_of(name: str, day: dt.date) -> str:
    return name[len(str(day)) + 1:-3]


def same_file(a: Path, b: Path) -> bool:
    sa, sb = a.stat(), b.stat()
    return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)


def copy_atomic(src: Path, dst: Path) -> None:
    """Copy under a temporary name the watcher ignores, then rename into place."""
    tmp = dst.with_name(f"~{dst.name}.tmp")
    shutil.copy2(src, tmp)                 # copy2 keeps the original modification time
    os.replace(tmp, dst)


def run_import(days=None, dry_run: bool = False, log=print) -> ImportResult:
    res = ImportResult()
    for day in days or campaign.campaign_days():
        folder = day_dir(day)
        try:
            ncs = sorted((e for e in os.scandir(folder) if e.name.endswith(".nc")),
                         key=lambda e: e.name)
        except FileNotFoundError:
            log(f"  no folder on Z:  {folder}")
            continue
        res.inventory[day] = [product_of(e.name, day) for e in ncs]
        jfiles = []
        for e in ncs:
            product, src = product_of(e.name, day), Path(e.path)
            if product.startswith(S.JVALUE_PREFIXES):
                jfiles.append(src)
            elif product in S.SAPHIR_IMPORT_PRODUCTS:
                dst = S.INCOMING / e.name
                archived = archive.original_path(e.name)     # moved there once accepted
                if any(p.exists() and same_file(src, p) for p in (dst, archived)):
                    res.current += 1
                    continue
                log(f"  {'replace' if dst.exists() else 'copy':<9s} {e.name}")
                if not dry_run:
                    copy_atomic(src, dst)
                res.copied.append(e.name)
            elif product not in S.SAPHIR_IGNORED_PRODUCTS:
                res.new_products[product].append(str(day))
        for product in S.SAPHIR_IMPORT_PRODUCTS:
            if product not in res.inventory[day]:
                res.missing.append(f"{day}.{product}")

        if jfiles:
            tok, inst = S.JVALUES_TOKEN
            out = S.INCOMING / f"{day}.{tok}.{inst}.csv"
            sig = jvalues.signature(jfiles)
            if sig in (jvalues.existing_signature(out),
                       jvalues.existing_signature(archive.original_path(out.name))):
                res.current += 1
            else:
                log(f"  {'rebuild' if out.exists() else 'build':<9s} {out.name} "
                    f"(from {len(jfiles)} j-value files)")
                if not dry_run:
                    jvalues.write(day, jfiles, S.INCOMING)
                res.built.append(out.name)
    return res


def print_inventory(res: ImportResult) -> None:
    days = sorted(res.inventory)
    grouped = defaultdict(lambda: defaultdict(int))
    for d in days:
        for p in res.inventory[d]:
            grouped[re.sub(r"\.j[A-Za-z0-9_]+$", ".j*", p)][d] += 1
    print(f"\n{'product':32s} " + " ".join(f"{d:%m%d}" for d in days))
    for p in sorted(grouped):
        print(f"{p:32s} " + " ".join(f"{grouped[p].get(d, '') or '.':>4}" for d in days))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="only report what would happen")
    ap.add_argument("--inventory", action="store_true", help="print products per day (implies --dry-run)")
    ap.add_argument("--days", nargs="+", type=dt.date.fromisoformat,
                    help="specific UTC days (default: every campaign day)")
    args = ap.parse_args(argv)
    if not S.INCOMING.exists():
        sys.exit(f"Incoming folder not found: {S.INCOMING}")

    dry = args.dry_run or args.inventory
    res = run_import(args.days, dry_run=dry)
    if args.inventory:
        print_inventory(res)
    verb = "would" if dry else "did"
    print(f"\n{verb} copy {len(res.copied)}, {verb} build {len(res.built)} J-value file(s), "
          f"up to date {res.current}")
    if res.missing:
        print(f"Not (yet) on Z: {len(res.missing)}: " + ", ".join(res.missing))
    for p, ds in sorted(res.new_products.items()):
        print(f"NEW ON Z (not imported): {p} on {', '.join(ds)}. Add it to "
              "SAPHIR_IMPORT_PRODUCTS or SAPHIR_IGNORED_PRODUCTS in settings.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
