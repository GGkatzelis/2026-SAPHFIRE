"""Archive cycle in a temporary sciebo folder: archive, re-upload (v2), identical
re-upload, rejected file stays pending, native SAPHIR + HDF5 to CSV, status page."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import settings as S  # noqa: E402

DAY = "2026-07-02"            # E02 in the campaign workbook
META = """instrument = PTRMS
institution = FZJ
data_format = csv
pi_name = Ada Lovelace
pi_email = a.lovelace@fz-juelich.de
coauthors = Grace Hopper <g.hopper@fz-juelich.de>
integration_time_s = 10
time_reference = start
"""


@pytest.fixture
def sciebo(tmp_path, monkeypatch):
    inc, arc = tmp_path / "Incoming - Upload", tmp_path / "Archive - Download"
    inc.mkdir()
    arc.mkdir()
    for k, v in {"INCOMING": inc, "ARCHIVE": arc, "ARCHIVE_METADATA": arc / "Metadata",
                 "ARCHIVE_ORIGINALS": arc / "_Originals", "ARCHIVE_LOG": arc / "archive_log.csv",
                 "STATUS_HTML": tmp_path / "status.html"}.items():
        monkeypatch.setattr(S, k, v)
    return inc, arc


def _csv(inc: Path, scale=1.0, name=f"{DAY}.PTRMS.FZJ.csv") -> Path:
    t = pd.date_range(f"{DAY} 06:00:00", periods=50, freq="10s").strftime("%Y-%m-%d %H:%M:%S")
    df = pd.DataFrame({"time_utc": t, "C5H8 [ppbv]": np.linspace(0.1, 2, 50) * scale})
    p = inc / name
    p.write_text("# team note: preliminary\n" + df.to_csv(index=False, float_format="%.5f"))
    return p


def _log():
    with open(S.ARCHIVE_LOG, newline="") as fh:
        return list(csv.DictReader(fh))


def test_archive_cycle(sciebo):
    import archive
    inc, arc = sciebo
    (inc / "Metadata.PTRMS.FZJ.txt").write_text(META)
    src = _csv(inc)
    original_text = src.read_text()
    archive.run_archive(log=lambda m: None)

    folder = "2026-07-02_E02_Smoldering-Fire_Day"
    assert not list(inc.iterdir()), "accepted files must leave Incoming"
    assert (arc / "_Originals" / folder / src.name).read_text() == original_text
    assert (arc / "Metadata" / "Metadata.PTRMS.FZJ.txt").exists()
    harm = (arc / folder / src.name).read_text()
    assert "version = 1" in harm and "time_reference = start" in harm
    body = [l for l in harm.splitlines() if not l.startswith("#")]
    assert body == [l for l in original_text.splitlines() if l.strip() and not l.startswith("#")]
    assert "# team note: preliminary" in harm
    assert (arc / folder / "EXPERIMENT_INFO.txt").exists()

    # corrected re-upload -> v2, v1 original kept as superseded
    _csv(inc, scale=2.0)
    archive.run_archive(log=lambda m: None)
    rows = [r for r in _log() if r["file"] == src.name]
    assert [r["version"] for r in rows] == ["1", "2"]
    assert (arc / "_Originals" / folder / "_superseded" / f"{src.stem}.v1.csv").exists()
    assert "version = 2" in (arc / folder / src.name).read_text()

    # identical re-upload -> no new version, removed from Incoming
    (inc / src.name).write_bytes((arc / "_Originals" / folder / src.name).read_bytes())
    archive.run_archive(log=lambda m: None)
    assert len([r for r in _log() if r["file"] == src.name]) == 2
    assert not (inc / src.name).exists()


def test_rejected_and_review_stay_pending(sciebo):
    import archive
    import overview
    inc, arc = sciebo
    (inc / "Metadata.PTRMS.FZJ.txt").write_text(META)
    bad = inc / f"{DAY}.PTRMS.FZJ.csv"
    bad.write_text(f"time_utc,mz69.069 [ppbv]\n{DAY} 06:00:00,1.0\n")
    archive.run_archive(log=lambda m: None)
    assert bad.exists(), "REJECTED stays in Incoming"
    html = overview.render()
    assert "Needs fixing" in html and "PTR-ToF-MS" in html


def test_approve_needs_confirmation(sciebo):
    import archive
    inc, arc = sciebo
    (inc / "Metadata.PTRMS.FZJ.txt").write_text(META)
    z = np.r_[np.zeros(10), np.ones(40)]
    p = _csv(inc)
    df = pd.read_csv(p, comment="#")
    df["C5H8 [ppbv]"] = z
    p.write_text(df.to_csv(index=False))
    archive.run_archive(log=lambda m: None)
    assert p.exists(), "NEEDS CONFIRMATION stays pending"
    archive.run_archive(approve=[p.name], log=lambda m: None)
    assert not p.exists() and _log()[-1]["how"] == "approved"


def test_team_fix_list_groups_days(sciebo):
    """Two days with the same mistake -> one team message, one item, both files named."""
    from feedback import team_messages
    from validator import evaluate_file
    inc, arc = sciebo
    (inc / "Metadata.PTRMS.FZJ.txt").write_text(META)
    files = []
    for day in ("2026-07-02", "2026-07-03"):
        p = inc / f"{day}.PTRMS.FZJ.csv"
        p.write_text(f"time_utc,mz69.069 [ppbv],C5H8 [ppbv]\n{day} 06:00:00,1.0,2.0\n")
        files.append(p)
    msgs = team_messages([evaluate_file(p, inc) for p in files])
    assert len(msgs) == 1 and msgs[0].team == "PTRMS (FZJ)"
    ion = [i for i in msgs[0].items if "ion mass" in i.title]
    assert len(ion) == 1 and ion[0].blocking and len(ion[0].files) == 2
    assert "Lovelace" in msgs[0].contact and "MUST BE FIXED" in msgs[0].text
    assert "Dear" not in msgs[0].text and "Best regards" not in msgs[0].text


def test_native_saphir_nc_to_csv(sciebo):
    import netCDF4
    import archive
    inc, arc = sciebo
    p = inc / "2026-07-03.SAPHIR.collected.all_param.nc"
    with netCDF4.Dataset(p, "w") as nc:
        nc.createDimension("time", 3)
        t = nc.createVariable("time", "f8", ("time",))
        t.units = "seconds since 2000-01-01 00:00:00 UTC"
        t.description = "Center of time interval."
        t0 = (pd.Timestamp("2026-07-03 00:00:30") - pd.Timestamp("2000-01-01")).total_seconds()
        t[:] = t0 + 60 * np.arange(3)
        v = nc.createVariable("p_SAPHIR", "f4", ("time",), fill_value=np.float32(np.nan))
        v.units = "hPa"
        v[:] = [1000.5, np.nan, 1001.25]
        nc.createVariable("p_SAPHIR@STDEV", "f4", ("time",))[:] = [0.1, 0.2, 0.3]
        nc.createVariable("p_SAPHIR@NO_OF_POINTS", "i4", ("time",))[:] = [6, 6, 6]
        r = nc.createVariable("roof_all", "f4", ("time",))
        r.units = " "
        r[:] = [1, 0, 0]
    archive.run_archive(log=lambda m: None)
    out = arc / "2026-07-03_E03_Flaming-Fire_Day" / "2026-07-03.SAPHIR.collected.all_param.csv"
    lines = [l for l in out.read_text().splitlines() if not l.startswith("#")]
    assert lines[0] == "time_utc,p_SAPHIR [hPa],p_SAPHIR_STDEV [hPa],roof_all [1]"
    assert lines[1].startswith("2026-07-03 00:00:30,1000.5,") and lines[2].split(",")[1] == ""
    assert "time_reference = centre" in out.read_text()


def test_h5_size_distribution_to_csv(tmp_path):
    """Two times and two bins on purpose: the bin axis must not be read as a time series."""
    import h5py
    from harmonise import harmonised_text
    p = tmp_path / f"{DAY}.SMPS-AMS.PATRAS.h5"
    t0 = pd.Timestamp(f"{DAY} 06:00:00").timestamp()
    with h5py.File(p, "w") as f:
        f.create_dataset("time_utc", data=t0 + 60.0 * np.arange(2)).attrs["units"] = \
            "seconds since 1970-01-01 00:00:00 UTC"
        f.create_dataset("dNdlogDp", data=np.array([[1, 2], [3, 4]], "f4")).attrs["units"] = "cm-3"
        f.create_dataset("diameter", data=np.array([14.6, 20.0], "f4")).attrs["units"] = "nm"
        f.create_dataset("Ntot", data=np.array([5, 6], "f4")).attrs["units"] = "cm-3"
    lines = [l for l in harmonised_text(p, []).splitlines() if not l.startswith("#")]
    assert lines[0] == "time_utc,Ntot [cm-3],dNdlogDp 14.6nm [cm-3],dNdlogDp 20nm [cm-3]"
    assert lines[1] == f"{DAY} 06:00:00,5,1,2"
