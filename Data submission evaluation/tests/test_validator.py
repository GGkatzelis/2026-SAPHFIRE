"""Synthetic good and broken submissions: each rule must fire on its own mistake.

Run:  ...\\.venv\\Scripts\\python.exe -m pytest "Data submission evaluation\\tests" -q
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validator import evaluate_file  # noqa: E402

DAY = "2026-07-02"
META = """# Metadata.PTRMS.FZJ.txt
instrument = PTRMS
institution = FZJ
data_format = csv
pi_name = Ada Lovelace
pi_email = a.lovelace@fz-juelich.de
coauthors = Grace Hopper <g.hopper@fz-juelich.de>; Alan Turing <a.turing@fz-juelich.de>;
integration_time_s = 10
time_reference = start   # start or centre
"""


def _times(n=200, step=10, start=f"{DAY} 06:00:00"):
    return pd.date_range(start, periods=n, freq=f"{step}s").strftime("%Y-%m-%d %H:%M:%S")


def _good_csv(tmp: Path, name=f"{DAY}.PTRMS.FZJ.csv", meta=META, **cols) -> Path:
    t = _times()
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"time_utc": t, "C5H8 [ppbv]": rng.uniform(0.1, 2, len(t)),
                       "C10H16 [pptv]": rng.uniform(1, 50, len(t))})
    for k, v in cols.items():
        df[k] = v
    p = tmp / name
    p.write_text("# test file\n" + df.to_csv(index=False, float_format="%.4f"), encoding="utf-8")
    if meta is not None:
        (tmp / "Metadata.PTRMS.FZJ.txt").write_text(meta)
    return p


def _msgs(rep, status):
    return " | ".join(c.message for c in rep.checks if c.status == status)


def test_good_csv_accepted(tmp_path):
    rep = evaluate_file(_good_csv(tmp_path), tmp_path)
    assert rep.verdict == "ACCEPTED", _msgs(rep, "FAIL") + _msgs(rep, "WARN")


def test_good_metadata_accepted(tmp_path):
    _good_csv(tmp_path)
    rep = evaluate_file(tmp_path / "Metadata.PTRMS.FZJ.txt", tmp_path)
    assert rep.verdict == "ACCEPTED", _msgs(rep, "FAIL") + _msgs(rep, "WARN")


@pytest.mark.parametrize("name", ["2026-07-02_PTRMS_FZJ.csv", "2026-07-02.PTRMS.FZJ.v2.csv",
                                  "02.07.2026.PTRMS.FZJ.csv", "2026-07-02.PTR-MS.FZJ.csv",
                                  "2026-07-02.ptrms.FZJ.csv"])
def test_bad_filenames(tmp_path, name):
    rep = evaluate_file(_good_csv(tmp_path, name=name), tmp_path)
    assert any(c.status == "FAIL" and "Rule 1" in c.rule for c in rep.checks)


def test_unregistered_tokens_only_warn(tmp_path):
    """Token list is open: a new instrument/institution is a WARN, not a rejection."""
    rep = evaluate_file(_good_csv(tmp_path, name=f"{DAY}.EESI.Juelich.csv"), tmp_path)
    assert not any(c.status == "FAIL" and "Rule 1" in c.rule for c in rep.checks)
    assert "not registered yet" in _msgs(rep, "WARN")


def test_saphir_native_name_not_a_team_file():
    import rules as R
    assert R.SAPHIR_NATIVE_RE.match("2026-07-07.ASS_METEO.all_param.nc")
    assert R.SAPHIR_NATIVE_RE.match("2026-07-07.SAPHIR.collected.all_param.nc")
    assert not R.SAPHIR_NATIVE_RE.match("2026-07-07.PTRMS.FZJ.nc")


def test_semicolon_rejected(tmp_path):
    p = tmp_path / f"{DAY}.PTRMS.FZJ.csv"
    p.write_text(f"time_utc;C5H8 [ppbv]\n{DAY} 06:00:00;1,5\n")
    (tmp_path / "Metadata.PTRMS.FZJ.txt").write_text(META)
    rep = evaluate_file(p, tmp_path)
    assert "German Excel" in _msgs(rep, "FAIL")


def test_decimal_comma_field_count(tmp_path):
    p = tmp_path / f"{DAY}.PTRMS.FZJ.csv"
    p.write_text(f"time_utc,C5H8 [ppbv]\n{DAY} 06:00:00,1,5\n{DAY} 06:00:10,1.6\n")
    (tmp_path / "Metadata.PTRMS.FZJ.txt").write_text(META)
    rep = evaluate_file(p, tmp_path)
    assert "comma-separated fields" in _msgs(rep, "FAIL")


def test_missing_brackets_and_ion_mass(tmp_path):
    rep = evaluate_file(_good_csv(tmp_path, **{"isoprene": 1.0, "mz69.069 [ppbv]": 1.0}), tmp_path)
    fails = _msgs(rep, "FAIL")
    assert "no unit in square brackets" in fails and "ion mass" in fails


def test_odd_hydrogen_warns(tmp_path):
    rep = evaluate_file(_good_csv(tmp_path, **{"C5H9 [ppbv]": 1.0}), tmp_path)
    assert "closed-shell" in _msgs(rep, "WARN")


def test_superscript_and_empty_unit(tmp_path):
    rep = evaluate_file(_good_csv(tmp_path, **{"C5H10 [µg m⁻³]": 1.0, "C6H6 []": 1.0}), tmp_path)
    fails = _msgs(rep, "FAIL")
    assert "non-ASCII" in fails and "empty unit" in fails


def test_fill_values_and_text(tmp_path):
    v = np.full(200, 1.0, dtype=object)
    v[5] = -9999
    w = np.full(200, "1.0", dtype=object)
    w[7] = "N/A"
    rep = evaluate_file(_good_csv(tmp_path, **{"C6H6 [ppbv]": v, "C7H8 [ppbv]": w}), tmp_path)
    fails = _msgs(rep, "FAIL")
    assert "fill values" in fails and "not a number" in fails


def test_negative_noise_is_not_a_fill_value(tmp_path):
    """OH in cm-3 scatters to -1e5 around zero: fine. A repeated -1111 is a fill value."""
    rng = np.random.default_rng(1)
    noise = rng.normal(0, 2e5, 200)
    fill = np.r_[np.full(5, -1111.0), np.ones(195)]
    rep = evaluate_file(_good_csv(tmp_path, **{"OH [cm-3]": noise, "C6H6 [ppbv]": fill}), tmp_path)
    warns = _msgs(rep, "WARN")
    assert "repeats in 1 column" in warns and "OH [cm-3]" not in " ".join(
        e for c in rep.checks for e in c.examples if "repeats" in c.message)


def test_zeros_warn_only(tmp_path):
    z = np.r_[np.zeros(50), np.ones(150)]
    rep = evaluate_file(_good_csv(tmp_path, **{"C6H6 [ppbv]": z}), tmp_path)
    assert rep.verdict == "NEEDS CONFIRMATION" and "Exact zeros" in _msgs(rep, "WARN")


def test_local_time_spillover(tmp_path):
    p = _good_csv(tmp_path)
    t = _times(n=200, step=30, start=f"{DAY} 23:00:00")      # runs into the next day
    df = pd.DataFrame({"time_utc": t, "C5H8 [ppbv]": 1.0})
    p.write_text(df.to_csv(index=False))
    rep = evaluate_file(p, tmp_path)
    assert "not on 2026-07-02" in _msgs(rep, "FAIL")


@pytest.mark.parametrize("bad", ["2026-07-02T06:00:00", "2026-07-02 06:00:00+02:00",
                                 "02.07.2026 06:00:00", "46205.25"])
def test_bad_time_formats(tmp_path, bad):
    p = _good_csv(tmp_path)
    p.write_text(f"time_utc,C5H8 [ppbv]\n{bad},1.0\n")
    rep = evaluate_file(p, tmp_path)
    assert any(c.status == "FAIL" and "Rule 3" in c.rule for c in rep.checks)


def test_duplicates(tmp_path):
    p = _good_csv(tmp_path)
    p.write_text(f"time_utc,C5H8 [ppbv]\n{DAY} 06:00:00,1\n{DAY} 06:00:00,2\n{DAY} 06:00:10,3\n")
    rep = evaluate_file(p, tmp_path)
    assert "duplicated timestamp" in _msgs(rep, "FAIL")


def test_time_utc_end(tmp_path):
    p = _good_csv(tmp_path)
    p.write_text(f"time_utc,time_utc_end,OP [a.u.]\n{DAY} 06:00:00,{DAY} 08:00:00,1\n"
                 f"{DAY} 09:00:00,{DAY} 08:30:00,2\n")
    rep = evaluate_file(p, tmp_path)
    assert "before time_utc" in _msgs(rep, "FAIL")


def test_missing_metadata(tmp_path):
    rep = evaluate_file(_good_csv(tmp_path, meta=None), tmp_path)
    assert "No metadata file" in _msgs(rep, "FAIL")


def test_subfolder(tmp_path):
    sub = tmp_path / "myteam"
    sub.mkdir()
    rep = evaluate_file(_good_csv(sub), tmp_path)
    assert "subfolder" in _msgs(rep, "FAIL")


def test_excel_rejected(tmp_path):
    p = tmp_path / f"{DAY}.PTRMS.FZJ.xlsx"
    p.write_bytes(b"PK")
    assert evaluate_file(p, tmp_path).verdict == "REJECTED"


def test_metadata_two_institutions(tmp_path):
    """FZJ data with a UOW PI: listing both institutions resolves the warning."""
    p = tmp_path / "Metadata.PTRMS.FZJ.txt"
    base = META.replace("a.lovelace@fz-juelich.de", "ada@uow.edu.au")
    p.write_text(base)
    assert "If both institutions" in _msgs(evaluate_file(p, tmp_path), "WARN")
    p.write_text(base.replace("institution = FZJ", "institution = FZJ; UOW"))
    rep = evaluate_file(p, tmp_path)
    assert rep.verdict == "ACCEPTED", _msgs(rep, "WARN") + _msgs(rep, "FAIL")
    assert "credited to 2 institutions" in _msgs(rep, "PASS")
    p.write_text(base.replace("institution = FZJ", "institution = UOW"))
    assert "does not include the filename token" in _msgs(evaluate_file(p, tmp_path), "FAIL")


def test_metadata_problems(tmp_path):
    p = tmp_path / "Metadata.PTRMS.FZJ.txt"
    p.write_text("instrument = PTRMS\ninstitution = UOW\npi_name = X\npi_email = x@uow.edu.au\n"
                 "coauthors = G. Gkatzelis <g@fz-juelich.de>; Someone\ntime_reference = end\n")
    rep = evaluate_file(p, tmp_path)
    fails, warns = _msgs(rep, "FAIL"), _msgs(rep, "WARN")
    assert "does not include the filename token" in fails
    assert "'start' or 'centre'" in fails
    assert "Full Name <email>" in fails
    assert "initials" in warns


# --- HDF5 ------------------------------------------------------------------------
def _h5(tmp: Path, flat=True, epoch=True, units=True, bins=True) -> Path:
    import h5py
    (tmp / "Metadata.SMPS-AMS.PATRAS.txt").write_text(
        META.replace("PTRMS", "SMPS-AMS").replace("institution = FZJ", "institution = PATRAS")
        .replace("data_format = csv", "data_format = h5"))
    p = tmp / f"{DAY}.SMPS-AMS.PATRAS.h5"
    n = 100
    t0 = pd.Timestamp(f"{DAY} 06:00:00").timestamp()
    with h5py.File(p, "w") as f:
        g = f if flat else f.create_group("data")
        d = g.create_dataset("time_utc", data=t0 + 10.0 * np.arange(n))
        if epoch:
            d.attrs["units"] = "seconds since 1970-01-01 00:00:00 UTC"
        n_tot = g.create_dataset("Ntot", data=np.ones(n, "f4"))
        if units:
            n_tot.attrs["units"] = "cm-3"
        if bins:
            g.create_dataset("dNdlogDp", data=np.ones((n, 5), "f4")).attrs["units"] = "cm-3"
            g.create_dataset("diameter", data=np.array([10, 20, 40, 80, 160], "f4")).attrs["units"] = "nm"
    return p


def test_h5_good(tmp_path):
    rep = evaluate_file(_h5(tmp_path), tmp_path)
    assert rep.verdict == "ACCEPTED", _msgs(rep, "FAIL") + _msgs(rep, "WARN")


@pytest.mark.parametrize("kw,expect", [({"flat": False}, "group"), ({"epoch": False}, "epoch"),
                                       ({"units": False}, "empty unit")])
def test_h5_bad(tmp_path, kw, expect):
    rep = evaluate_file(_h5(tmp_path, **kw), tmp_path)
    assert rep.verdict == "REJECTED" and expect in _msgs(rep, "FAIL")
