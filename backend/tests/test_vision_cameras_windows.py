"""Windows camera identification from OS metadata (no camera is opened).

FIXTURE CAVEAT (data-contract rule): these records are built from the documented `Win32_PnPEntity`
CIM schema (`Get-CimInstance Win32_PnPEntity | Select Name,PNPDeviceID,PNPClass,Status |
ConvertTo-Json`), NOT captured from the lab PC — there was no access to it when this was written.
They are SHAPE-ONLY tests. Replace with a real capture from the Windows PC once available.
"""

import json
import subprocess
from unittest.mock import patch

from vention_printer_interface.vision.cameras import _metadata_devices, _parse_windows_cameras

ELP_A = {"Name": "ELP 4K USB Camera", "PNPClass": "Camera", "Status": "OK",
         "PNPDeviceID": "USB\\VID_32E4&PID_2020&MI_00\\7&1A2B3C4D&0&0000"}
ELP_B = {"Name": "ELP 4K USB Camera", "PNPClass": "Camera", "Status": "OK",
         "PNPDeviceID": "USB\\VID_32E4&PID_2020&MI_00\\7&5E6F7A8B&0&0000"}
BUILTIN = {"Name": "Integrated Camera", "PNPClass": "Camera", "Status": "OK",
           "PNPDeviceID": "USB\\VID_04F2&PID_B6D9&MI_00\\6&11111111&0&0000"}
SCANNER = {"Name": "EPSON Scanner", "PNPClass": "Image", "Status": "OK",
           "PNPDeviceID": "USB\\VID_04B8&PID_0142\\5&22222222&0&4"}
HUB = {"Name": "USB Root Hub", "PNPClass": "USB", "Status": "OK",
       "PNPDeviceID": "USB\\ROOT_HUB30\\4&33333333&0&0"}


def test_parse_lists_cameras_with_names_stable_ids_and_vid_pid() -> None:
    devs = _parse_windows_cameras([ELP_A, ELP_B, BUILTIN, SCANNER, HUB])
    names = [d["name"] for d in devs]
    # scanner + USB hub are dropped; the built-in stays (listed, but not assignable)
    assert names == ["ELP 4K USB Camera", "ELP 4K USB Camera", "Integrated Camera"]
    assert [d["index"] for d in devs] == [0, 1, 2]
    # PnP instance path is stable across reboots and tells two identical ELPs apart
    assert devs[0]["stable_id"] == "win-pnp:" + ELP_A["PNPDeviceID"]
    assert devs[0]["stable_id"] != devs[1]["stable_id"]
    # VID:PID in DECIMAL, matching macOS (VendorID_13028), so the identical-model guard agrees
    assert devs[0]["vid_pid"] == f"{0x32E4}:{0x2020}"
    # identification only — never opened, so access is not yet verified
    assert all(d["has_frame"] is None and d["probed"] is False for d in devs)


def test_parse_marks_builtin_camera_not_assignable() -> None:
    devs = {d["name"]: d for d in _parse_windows_cameras([ELP_A, BUILTIN])}
    assert devs["ELP 4K USB Camera"]["assignable"] is True
    assert devs["Integrated Camera"]["assignable"] is False


def test_parse_accepts_a_single_object() -> None:
    # PowerShell's ConvertTo-Json emits a bare object (not a list) when exactly one device matches.
    devs = _parse_windows_cameras(ELP_A)
    assert len(devs) == 1 and devs[0]["name"] == "ELP 4K USB Camera"


def test_parse_tolerates_junk() -> None:
    assert _parse_windows_cameras(None) == []
    assert _parse_windows_cameras([1, "x", {"PNPClass": "Camera"}]) == [
        {"index": 0, "stable_id": "idx:0", "name": None, "vid_pid": None, "assignable": False,
         "status": None, "has_frame": None, "probed": False}
    ]


def test_metadata_devices_on_windows_queries_powershell_without_opening_cameras() -> None:
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout=json.dumps([ELP_A, ELP_B]))
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.run", return_value=fake) as run:
        devs = _metadata_devices()
    assert [d["name"] for d in devs] == ["ELP 4K USB Camera", "ELP 4K USB Camera"]
    cmd = " ".join(run.call_args.args[0])
    assert "powershell" in cmd.lower() and "Win32_PnPEntity" in cmd


def test_metadata_devices_on_windows_never_raises() -> None:
    with patch("platform.system", return_value="Windows"), \
         patch("subprocess.run", side_effect=OSError("powershell missing")):
        assert _metadata_devices() == []
