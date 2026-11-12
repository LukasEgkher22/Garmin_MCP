"""Merge several Garmin .fit activity files into one activity (no dependencies).

Works on the raw FIT messages, so everything the watch recorded (GPS, HR,
power, running dynamics, Garmin's own undocumented messages) is copied as-is.
Only these things change:

* file_id / file_creator / settings come from the first file only
* record distances of later files are shifted so distance keeps counting up
* laps are renumbered 0..n-1, so all laps are kept
* the time between files is a pause (each file already ends with "timer stop"
  and starts with "timer start")
* per-file session, activity, splits and time-in-zone summaries are dropped,
  and one new session + activity with recalculated totals is written
"""

from __future__ import annotations

import datetime as dt
import struct
from dataclasses import dataclass
from pathlib import Path

FIT_EPOCH = 631065600  # 1989-12-31 00:00:00 UTC in unix seconds

# Global message numbers
FILE_ID, FILE_CREATOR, LAP, RECORD, EVENT, SESSION, ACTIVITY = 0, 49, 19, 20, 21, 18, 34
DEVICE_INFO, HRV, LENGTH, GPS_METADATA = 23, 78, 101, 160
FIELD_DESCRIPTION, DEVELOPER_DATA_ID = 206, 207
ONCE = {FILE_ID, FILE_CREATOR, 2, 3, 7, 8, 9, 12, 13, 15}  # settings: first file only
DROP = {SESSION, ACTIVITY, 216, 312, 313}  # summaries we rebuild or that would be wrong
STREAM = {LAP, RECORD, EVENT, DEVICE_INFO, HRV, LENGTH, GPS_METADATA}  # kept from every file
TIMESTAMP, MESSAGE_INDEX = 253, 254

# base type -> (struct code, invalid value)
_INT = {
    0x00: ("B", 0xFF), 0x01: ("b", 0x7F), 0x02: ("B", 0xFF), 0x0A: ("B", 0x00),
    0x83: ("h", 0x7FFF), 0x84: ("H", 0xFFFF), 0x8B: ("H", 0x0000),
    0x85: ("i", 0x7FFFFFFF), 0x86: ("I", 0xFFFFFFFF), 0x8C: ("I", 0x00000000),
    0x8E: ("q", 0x7FFFFFFFFFFFFFFF), 0x8F: ("Q", 0xFFFFFFFFFFFFFFFF), 0x90: ("Q", 0),
}


class FitError(ValueError):
    pass


def _crc(data: bytes, crc: int = 0) -> int:
    table = (0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
             0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400)
    for b in data:
        tmp = table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ table[b & 0xF]
        tmp = table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ table[(b >> 4) & 0xF]
    return crc


@dataclass(frozen=True)
class Definition:
    global_num: int
    big_endian: bool
    fields: tuple[tuple[int, int, int], ...]  # (field num, size, base type)
    dev_fields: tuple[tuple[int, int, int], ...] = ()  # (field num, size, developer index)

    def offset(self, num: int) -> tuple[int, int, int] | None:
        off = 0
        for n, size, base in self.fields:
            if n == num:
                return off, size, base
            off += size
        return None

    @property
    def size(self) -> int:
        return sum(f[1] for f in self.fields) + sum(f[1] for f in self.dev_fields)

    def encode(self) -> bytes:
        out = bytes([0, int(self.big_endian)]) + self.global_num.to_bytes(2, "big" if self.big_endian else "little")
        out +=bytes([len(self.fields)]) + b"".join(bytes(f) for f in self.fields)
        if self.dev_fields:
            out += bytes([len(self.dev_fields)]) + b"".join(bytes(f) for f in self.dev_fields)
        return out


@dataclass
class Message:
    defn: Definition
    data: bytearray

    @property
    def num(self) -> int:
        return self.defn.global_num

    def get(self, num: int) -> int | None:
        loc = self.defn.offset(num)
        if not loc or loc[2] not in _INT:
            return None
        off, size, base = loc
        code, invalid = _INT[base]
        if struct.calcsize(code) != size:
            return None
        v = struct.unpack((">" if self.defn.big_endian else "<") + code, self.data[off:off + size])[0]
        return None if v == invalid else v

    def set(self, num: int, value: int) -> bool:
        loc = self.defn.offset(num)
        if not loc or loc[2] not in _INT:
            return False
        off, size, base = loc
        code = _INT[base][0]
        if struct.calcsize(code) != size:
            return False
        self.data[off:off + size] = struct.pack((">" if self.defn.big_endian else "<") + code, value)
        return True

    def strip_dev(self) -> Message:
        if not self.defn.dev_fields:
            return self
        d = Definition(self.defn.global_num, self.defn.big_endian, self.defn.fields)
        return Message(d, bytearray(self.data[:d.size]))


@dataclass
class FitFile:
    path: Path
    protocol: int
    profile: int
    messages: list[Message]

    def of(self, num: int) -> list[Message]:
        return [m for m in self.messages if m.num == num]


def read_fit(path: str | Path) -> FitFile:
    """Parse one FIT file into raw messages (compressed timestamps are expanded)."""
    path = Path(path)
    buf = path.read_bytes()
    if len(buf) < 14 or buf[8:12] != b".FIT":
        raise FitError(f"{path.name} is not a FIT file")
    hsize, protocol = buf[0], buf[1]
    profile = struct.unpack_from("<H", buf, 2)[0]
    data_size = struct.unpack_from("<I", buf, 4)[0]
    end = hsize + data_size
    if end + 2 > len(buf):
        raise FitError(f"{path.name} is truncated")
    if _crc(buf[:end + 2]) != 0:
        raise FitError(f"{path.name} has a bad checksum")

    local: dict[int, Definition] = {}
    msgs: list[Message] = []
    last_ts = 0
    pos = hsize
    while pos < end:
        h = buf[pos]
        pos += 1
        if h & 0x80:  # compressed timestamp header
            lt, off5 = (h >> 5) & 0x03, h & 0x1F
            base = local.get(lt)
            if base is None:
                raise FitError(f"{path.name}: data before definition at byte {pos}")
            ts = (last_ts & ~0x1F) + off5 + (0x20 if off5 < (last_ts & 0x1F) else 0)
            last_ts = ts
            raw = buf[pos:pos + base.size]
            pos += base.size
            d = Definition(base.global_num, base.big_endian, ((TIMESTAMP, 4, 0x86),) + base.fields, base.dev_fields)
            msgs.append(Message(d, bytearray(ts.to_bytes(4, "big" if d.big_endian else "little") + raw)))
            continue
        lt = h & 0x0F
        if h & 0x40:  # definition
            big = buf[pos + 1] == 1
            gnum = int.from_bytes(buf[pos + 2:pos + 4], "big" if big else "little")
            n = buf[pos + 4]
            pos += 5
            fields = tuple(tuple(buf[pos + 3 * i:pos + 3 * i + 3]) for i in range(n))
            pos += 3 * n
            dev: tuple = ()
            if h & 0x20:
                nd = buf[pos]
                pos += 1
                dev = tuple(tuple(buf[pos + 3 * i:pos + 3 * i + 3]) for i in range(nd))
                pos += 3 * nd
            local[lt] = Definition(gnum, big, fields, dev)  # type: ignore[arg-type]
        else:
            d = local.get(lt)
            if d is None:
                raise FitError(f"{path.name}: data before definition at byte {pos}")
            m = Message(d, bytearray(buf[pos:pos + d.size]))
            pos += d.size
            ts = m.get(TIMESTAMP)
            if ts is not None:
                last_ts = ts
            msgs.append(m)
    return FitFile(path, protocol, profile, msgs)


def write_fit(path: str | Path, messages: list[Message], protocol: int = 0x20, profile: int = 2100) -> None:
    body = bytearray()
    slots: dict[int, Definition] = {}
    by_defn: dict[Definition, int] = {}
    next_slot = 0
    for m in messages:
        lt = by_defn.get(m.defn)
        if lt is None:
            lt = next_slot
            next_slot = (next_slot + 1) % 16
            old = slots.get(lt)
            if old is not None:
                del by_defn[old]
            slots[lt], by_defn[m.defn] = m.defn, lt
            body += bytes([0x40 | (0x20 if m.defn.dev_fields else 0) | lt]) + m.defn.encode()
        body += bytes([lt]) + m.data
    header = bytearray(struct.pack("<BBHI4s", 14, protocol, profile, len(body), b".FIT"))
    header += struct.pack("<H", _crc(header))
    out = bytes(header) + bytes(body)
    Path(path).write_bytes(out + struct.pack("<H", _crc(out)))


# ------------------------------------------------------------------ merging

def _new(gnum: int, fields: list[tuple[int, int, int | None]]) -> Message:
    """Build a little-endian message from (field num, base type, value) triples."""
    defs, data = [], bytearray()
    for num, base, value in fields:
        code, invalid = _INT[base]
        defs.append((num, struct.calcsize(code), base))
        data += struct.pack("<" + code, invalid if value is None else int(value))
    return Message(Definition(gnum, False, tuple(defs)), data)


def _wavg(pairs: list[tuple[float | None, float]]) -> float | None:
    pairs = [(v, w) for v, w in pairs if v is not None and w > 0]
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def _sum(vals: list[int | None]) -> int | None:
    vals = [v for v in vals if v is not None]
    return sum(vals) if vals else None


def _max(vals: list[int | None]) -> int | None:
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def fit_time(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts + FIT_EPOCH, dt.timezone.utc).isoformat()


def merge_fit_files(paths: list[str | Path], out_path: str | Path) -> dict:
    """Merge activity FIT files into one activity. Returns a short summary."""
    if len(paths) < 2:
        raise FitError("Give at least two files to merge")
    files = [read_fit(p) for p in paths]

    info = []
    for f in files:
        sessions = f.of(SESSION)
        records = [i for i, m in enumerate(f.messages) if m.num == RECORD]
        if len(sessions) != 1:
            raise FitError(f"{f.path.name}: has {len(sessions)} sessions; only single-sport activities can be merged")
        if not records:
            raise FitError(f"{f.path.name}: has no records")
        s = sessions[0]
        first_ts = f.messages[records[0]].get(TIMESTAMP)
        last_ts = f.messages[records[-1]].get(TIMESTAMP)
        info.append({"file": f, "session": s, "first_rec": records[0], "last_rec": records[-1],
                     "start": s.get(2) or first_ts, "first_ts": first_ts, "last_ts": last_ts,
                     "sport": (s.get(5), s.get(6))})
    info.sort(key=lambda i: i["start"])

    sports = {i["sport"][0] for i in info}
    if len(sports) > 1:
        raise FitError("The activities are different sports and can't become one activity")
    for a, b in zip(info, info[1:]):
        if b["first_ts"] < a["last_ts"]:
            raise FitError(f"{a['file'].path.name} and {b['file'].path.name} overlap in time")

    # developer (Connect IQ) fields: keep them only where every file defines them the same way
    def dev_key(f: FitFile) -> tuple:
        return tuple(bytes(m.data) for m in f.messages if m.num in (FIELD_DESCRIPTION, DEVELOPER_DATA_ID))
    first_dev = dev_key(info[0]["file"])

    out: list[Message] = []
    lap_index = 0
    dist_offset = 0  # in FIT units (cm)
    for k, i in enumerate(info):
        f = i["file"]
        keep_dev = k == 0 or dev_key(f) == first_dev
        last_dist = None
        for pos, m in enumerate(f.messages):
            n = m.num
            if n in DROP:
                continue
            if n in ONCE or n in (FIELD_DESCRIPTION, DEVELOPER_DATA_ID):
                if k == 0:  # later files' copies are identical (keep_dev) or stripped
                    out.append(m)
                continue
            if n not in STREAM:  # undocumented Garmin message: keep header bits from file 1,
                if pos < i["first_rec"] and k > 0:  # stream bits from every file,
                    continue
                if pos > i["last_rec"]:  # and drop per-file end-of-activity summaries
                    continue
            m = Message(m.defn, bytearray(m.data)) if keep_dev else m.strip_dev()
            if n == RECORD:
                d = m.get(5)
                if d is not None:
                    last_dist = d
                    if dist_offset:
                        m.set(5, d + dist_offset)
            elif n == LAP:
                m.set(MESSAGE_INDEX, lap_index)
                lap_index += 1
            out.append(m)
        s = i["session"]
        dist_offset += s.get(9) if s.get(9) is not None else (last_dist or 0)

    # new file_id time so Garmin doesn't reject the upload as a duplicate of file 1
    now_fit = int(dt.datetime.now(dt.timezone.utc).timestamp()) - FIT_EPOCH
    for m in out:
        if m.num == FILE_ID:
            m.data = bytearray(m.data)
            m.set(4, now_fit)
            break

    # ---- recalculated session
    ss = [i["session"] for i in info]
    timer = [(s.get(8) or 0) / 1000 for s in ss]
    total_timer = sum(timer)
    end_ts = max(max(s.get(TIMESTAMP) or 0 for s in ss), info[-1]["last_ts"])
    start_ts = info[0]["start"]
    total_dist = _sum([s.get(9) for s in ss])  # cm
    recs = [m for m in out if m.num == RECORD]
    lats = [m.get(0) for m in recs if m.get(0) is not None and m.get(1) is not None]
    lons = [m.get(1) for m in recs if m.get(0) is not None and m.get(1) is not None]

    def spd(s: Message, enhanced: int, plain: int) -> int | None:
        return s.get(enhanced) if s.get(enhanced) is not None else s.get(plain)

    avg_speed = round(total_dist / 100 / total_timer * 1000) if total_dist and total_timer else None
    max_speed = _max([spd(s, 125, 15) for s in ss])

    def w(field: int) -> int | None:
        v = _wavg([(s.get(field), t) for s, t in zip(ss, timer)])
        return None if v is None else round(v)

    first, last = ss[0], ss[-1]
    session = _new(SESSION, [
        (TIMESTAMP, 0x86, end_ts),
        (2, 0x86, start_ts),
        (3, 0x85, first.get(3)), (4, 0x85, first.get(4)),
        (38, 0x85, last.get(38)), (39, 0x85, last.get(39)),
        (29, 0x85, max(lats) if lats else None), (30, 0x85, max(lons) if lons else None),
        (31, 0x85, min(lats) if lats else None), (32, 0x85, min(lons) if lons else None),
        (7, 0x86, (end_ts - start_ts) * 1000),
        (8, 0x86, round(total_timer * 1000)),
        (9, 0x86, total_dist),
        (10, 0x86, _sum([s.get(10) for s in ss])),
        (11, 0x84, _sum([s.get(11) for s in ss])),
        (14, 0x84, avg_speed if avg_speed is not None and avg_speed < 0xFFFF else None),
        (15, 0x84, max_speed if max_speed is not None and max_speed < 0xFFFF else None),
        (124, 0x86, avg_speed), (125, 0x86, max_speed),
        (16, 0x02, w(16)), (17, 0x02, _max([s.get(17) for s in ss])),
        (18, 0x02, w(18)), (19, 0x02, _max([s.get(19) for s in ss])),
        (20, 0x84, w(20)), (21, 0x84, _max([s.get(21) for s in ss])),
        (34, 0x84, w(34)),  # normalized power (approximate: time-weighted)
        (22, 0x84, _sum([s.get(22) for s in ss])), (23, 0x84, _sum([s.get(23) for s in ss])),
        (25, 0x84, 0), (26, 0x84, lap_index),
        (0, 0x00, 9), (1, 0x00, 1),  # event = lap, event_type = stop (as the watch writes it)
        (5, 0x00, first.get(5)), (6, 0x00, first.get(6)),
        (MESSAGE_INDEX, 0x84, 0),
    ])
    out.append(session)

    act0 = info[0]["file"].of(ACTIVITY)
    tz = 0
    if act0 and act0[0].get(5) is not None and act0[0].get(TIMESTAMP) is not None:
        tz = act0[0].get(5) - act0[0].get(TIMESTAMP)
    out.append(_new(ACTIVITY, [
        (TIMESTAMP, 0x86, end_ts),
        (0, 0x86, round(total_timer * 1000)),
        (1, 0x84, 1),
        (2, 0x00, 0),  # manual
        (3, 0x00, 26), (4, 0x00, 1),  # event = activity, event_type = stop
        (5, 0x86, end_ts + tz),
    ]))

    f0 = info[0]["file"]
    write_fit(out_path, out, f0.protocol, f0.profile)
    return {
        "out_path": str(Path(out_path).resolve()),
        "merged_from": [str(i["file"].path) for i in info],
        "start": fit_time(start_ts),
        "end": fit_time(end_ts),
        "distance_km": round((total_dist or 0) / 100_000, 2),
        "moving_time_min": round(total_timer / 60, 1),
        "elapsed_time_min": round((end_ts - start_ts) / 60, 1),
        "laps": lap_index,
        "records": len(recs),
    }
