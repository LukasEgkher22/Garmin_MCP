"""Turn a Garmin pool-swim .fit into an "interval" version for Strava.

Strava draws pool swims from the per-length data, which looks noisy. This
rewrites the file so every block you swam between two rests is one flat
segment at that block's average pace:

* length messages (one per 25/50 m) are dropped
* every swim lap gets its average speed filled in
* every record gets a distance and speed: distance grows evenly at the lap's
  average pace while you swim and stays flat while you rest
* each rest between two laps becomes its own 0 m lap marked "rest", so
  Strava's web view doesn't fold the rest into the next block

Everything else (heart rate, device info, Garmin's own messages) is copied
as-is. Built on fitmerge's reader/writer, no dependencies.
"""

from __future__ import annotations

from pathlib import Path

import fitmerge as fm
from fitmerge import LAP, LENGTH, MESSAGE_INDEX, RECORD, SESSION, TIMESTAMP, Definition, Message

SWIMMING, LAP_SWIMMING = 5, 17
REST = 1  # lap intensity "rest"
REC_DIST, REC_SPEED = 5, 73  # record.distance (cm), record.enhanced_speed (mm/s)


def is_pool_swim(path: str | Path) -> bool:
    f = fm.read_fit(path)
    s = f.of(SESSION)
    return len(s) == 1 and s[0].get(5) == SWIMMING and s[0].get(6) == LAP_SWIMMING


def _with_dist_fields(d: Definition) -> Definition:
    """Same record definition plus distance + enhanced_speed (before dev fields)."""
    extra = tuple(f for f in ((REC_DIST, 4, 0x86), (REC_SPEED, 4, 0x86)) if d.offset(f[0]) is None)
    return Definition(d.global_num, d.big_endian, d.fields + extra, d.dev_fields)


def _rest_lap(start: int, end_ms: int, index: int) -> Message:
    return fm._new(LAP, [
        (TIMESTAMP, 0x86, start + round(end_ms / 1000)),
        (2, 0x86, start),
        (7, 0x86, end_ms), (8, 0x86, end_ms),  # elapsed, timer (ms)
        (9, 0x86, 0),  # distance
        (13, 0x84, 0), (110, 0x86, 0),  # avg speed
        (0, 0x00, 9), (1, 0x00, 1),  # event lap, stop
        (23, 0x00, REST), (24, 0x00, 0),  # intensity rest, manual trigger
        (25, 0x00, SWIMMING), (39, 0x00, LAP_SWIMMING),
        (MESSAGE_INDEX, 0x84, index),
    ])


def to_intervals(src: str | Path, dst: str | Path) -> dict:
    """Write the interval version of a pool swim. Returns a short summary."""
    f = fm.read_fit(src)
    sessions = f.of(SESSION)
    if len(sessions) != 1 or sessions[0].get(5) != SWIMMING or sessions[0].get(6) != LAP_SWIMMING:
        raise fm.FitError(f"{Path(src).name} is not a single pool swim")

    # swim laps: (start s, timer s, distance m), in time order
    laps = []
    for m in f.of(LAP):
        start, timer, dist = m.get(2), m.get(8), m.get(9)
        if start is None or not timer or dist is None:
            continue
        laps.append((start, timer / 1000, dist / 100))
    laps.sort()
    if not laps:
        raise fm.FitError(f"{Path(src).name} has no swim laps")

    rests = []  # (start s, duration ms, next lap start s)
    for (s0, t0, _), (s1, _, _) in zip(laps, laps[1:]):
        end = s0 + t0
        if s1 - end >= 1:
            rests.append((round(end), round((s1 - end) * 1000), s1))

    def dist_speed(ts: int) -> tuple[float, float]:
        done = 0.0
        for s, t, d in laps:
            if ts < s:
                return done, 0.0
            if ts <= s + t:
                return done + d * (ts - s) / t, d / t
            done += d
        return done, 0.0

    defs: dict[Definition, Definition] = {}
    out: list[Message] = []
    lap_index = 0
    next_rest = 0
    for m in f.messages:
        n = m.num
        if n == LENGTH:
            continue
        if n == RECORD:
            ts = m.get(TIMESTAMP)
            while next_rest < len(rests) and ts is not None and ts >= rests[next_rest][2]:
                start, dur, _ = rests[next_rest]
                out.append(_rest_lap(start, dur, lap_index))
                lap_index += 1
                next_rest += 1
            nd = defs.setdefault(m.defn, _with_dist_fields(m.defn))
            reg = sum(fl[1] for fl in m.defn.fields)
            added = len(nd.fields) - len(m.defn.fields)
            m = Message(nd, bytearray(m.data[:reg]) + bytearray(4 * added) + bytearray(m.data[reg:]))
            if ts is not None:
                d, v = dist_speed(ts)
                m.set(REC_DIST, round(d * 100))
                m.set(REC_SPEED, round(v * 1000))
        elif n == LAP:
            m = Message(m.defn, bytearray(m.data))
            dist, timer = m.get(9), m.get(8)
            if dist is not None and timer:
                v = round(dist / 100 / (timer / 1000) * 1000)
                if v < 0xFFFF:
                    m.set(13, v)
                m.set(110, v)
            m.set(MESSAGE_INDEX, lap_index)
            lap_index += 1
        elif n == SESSION:
            m = Message(m.defn, bytearray(m.data))
        out.append(m)

    for m in out:
        if m.num == SESSION:
            m.set(26, lap_index)  # num_laps

    fm.write_fit(dst, out, f.protocol, f.profile)
    return {
        "out_path": str(Path(dst).resolve()),
        "swim_laps": len(laps),
        "rest_laps": len(rests),
        "distance_m": round(sum(d for _, _, d in laps)),
        "intervals": [{"m": round(d), "pace_per_100m": _pace(t / d * 100)} for _, t, d in laps if d > 0],
    }


def _pace(secs: float) -> str:
    s = round(secs)
    return f"{s // 60}:{s % 60:02d}"
