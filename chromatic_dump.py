#!/usr/bin/env python3
import argparse
import datetime as dt
import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / ".venv" / "bin" / "python"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else sys.executable)
FIRMWARE = ROOT / "evt1_x2.fs"
DUMPS = ROOT / "dumps"
RUNTIME_HOME = ROOT / ".chromatic_dump_home"


def run(cmd, capture=False, private_home=False):
    print("+ " + " ".join(map(str, cmd)), flush=True)
    env = os.environ.copy()
    if private_home:
        RUNTIME_HOME.mkdir(exist_ok=True)
        env["HOME"] = str(RUNTIME_HOME)
    return subprocess.run(
        list(map(str, cmd)),
        cwd=ROOT,
        env=env,
        text=True,
        check=True,
        capture_output=capture,
    )


def flashgbx(cmd, retries=1):
    last = ""
    for attempt in range(retries):
        result = run(cmd, capture=True, private_home=True)
        last = result.stdout + result.stderr
        if last:
            print(last, end="" if last.endswith("\n") else "\n")
        if "No devices found." not in last and "Couldn’t connect to the device." not in last:
            return last
        if attempt + 1 < retries:
            time.sleep(1)
    raise SystemExit("FlashGBX could not connect to the Chromatic.")


def flashgbx_args(port, action, path=None, extra=()):
    cmd = [
        PYTHON, "-m", "FlashGBX",
        "--cli", "--cfgdir", "appdata",
        "--mode", "dmg",
        "--action", action,
        "--device-port", port,
    ]
    cmd.extend(extra)
    if path is not None:
        cmd.append(path)
    return cmd


def pick_port(port):
    if port:
        return port
    ports = sorted(glob.glob("/dev/cu.usbmodem*"))
    if len(ports) == 1:
        return ports[0]
    raise SystemExit("Pass --port /dev/cu.usbmodem...; auto-detect found: " + ", ".join(ports))


def wait_for_port(port):
    deadline = time.time() + 10
    while time.time() < deadline:
        if Path(port).exists():
            return
        time.sleep(0.25)
    raise SystemExit(f"Serial port did not appear: {port}")


def field(text, name):
    match = re.search(rf"^{re.escape(name)}:\s*(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else ""


def slugify(name):
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()
    return slug or "unknown_game"


def main():
    parser = argparse.ArgumentParser(description="Save-only Chromatic dumper for FlashGBX.")
    parser.add_argument("--rom", action="store_true", help="also dump the ROM")
    parser.add_argument("--port", help="serial port, e.g. /dev/cu.usbmodem0123456783")
    parser.add_argument("--skip-firmware", action="store_true", help="do not reload evt1_x2.fs")
    args = parser.parse_args()

    port = pick_port(args.port)
    if not FIRMWARE.exists() and not args.skip_firmware:
        raise SystemExit(f"Missing firmware: {FIRMWARE}")

    if not args.skip_firmware:
        run(["openFPGALoader", "--cable", "gwu2x", "--write-sram", FIRMWARE])
        wait_for_port(port)
        time.sleep(2)

    info = flashgbx(flashgbx_args(port, "info"), retries=5)
    game_name = field(info, "Game Name") or field(info, "Game Title") or "Unknown Game"
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    game_dir = DUMPS / slugify(game_name)
    saves_dir = game_dir / "saves"
    saves_dir.mkdir(parents=True, exist_ok=True)

    save_path = saves_dir / f"{stamp}.sav"
    flashgbx(flashgbx_args(port, "backup-save", save_path), retries=3)
    if not save_path.exists() or save_path.stat().st_size == 0:
        raise SystemExit(f"Save dump did not create a non-empty file: {save_path}")

    if args.rom:
        roms_dir = game_dir / "roms"
        roms_dir.mkdir(parents=True, exist_ok=True)
        ext = "gbc" if field(info, "Game Boy Color") == "Supported" else "gb"
        rom_path = roms_dir / f"{stamp}.{ext}"
        flashgbx(flashgbx_args(port, "backup-rom", rom_path, extra=["--generate-dump-report"]), retries=3)
        if not rom_path.exists() or rom_path.stat().st_size == 0:
            raise SystemExit(f"ROM dump did not create a non-empty file: {rom_path}")

    print(f"\nSaved to: {game_dir}")
    print("Power off the Chromatic before swapping cartridges.")


if __name__ == "__main__":
    main()
