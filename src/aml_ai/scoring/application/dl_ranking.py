"""고정된 스캔의 ML·DL 점수로 조사 순위를 계산한다."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import re
from collections import OrderedDict
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from itertools import groupby
from math import isfinite
from pathlib import Path
from threading import Lock

from pydantic import BaseModel

from aml_ai.scoring.domain.dl_evidence import evidence_digest, reference_text
from aml_ai.shared.errors import AiError

_MAX_BYTES = 8 * 1024 * 1024
_MAX_ALERTS = 20_000
_MAX_CACHE_ENTRIES = 4
_ALERT_NO_SUFFIX_PATTERN = r"[0-9]{6,18}"
_EPOCH = datetime(2022, 9, 1)
_ONE_MINUTE = timedelta(minutes=1)
_ML_MODEL = "xgb-hi-medium-r04-event-c2-31-v1"
_ML_FEATURES = "hi-medium-evidence31-96h-r04-event-v1"
_DL_MODEL = "HI-Medium-B-GINe-counts-best-13"
_DL_COMMIT = "b75cf1e42d24a4a46ddff2f259dde5ac9a8c63c1"
_SCAN_FILES = ("alerts.csv", "evidence_transactions.csv", "history_24h.csv", "history_coverage.csv")
SNAPSHOT_FILES = frozenset(
    (
        "alerts.csv",
        "evidence_transactions.csv",
        "evidence_source_map.csv",
        "ml.csv",
        "ml-summary.json",
        "dl.csv",
        "dl-summary.json",
        "worker-input.json",
    )
)


class RankingUnavailable(AiError):
    status, code = 503, "DL_RANKING_UNAVAILABLE"


class RankedAlert(BaseModel):
    alert_id: str
    rule_id: str
    ml_score: float | None
    ml_failure_code: str | None
    dl_score: float | None
    evidence_count: int
    dl_linked: int
    fallback_reason: str | None
    ml_rank: int | None
    fused_rank: int | None
    reference_ts: str
    evidence_digest: str


class ReviewRanking(BaseModel):
    scan_date: date
    snapshot_sha256: str
    ml_model: str
    dl_model: str
    evidence_transactions: int
    scored_transactions: int
    linked_alerts: int
    ml_only_alerts: int
    unscored_alerts: int
    alerts: list[RankedAlert]


class SnapshotInvalid(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class CachedRanking:
    hashes: dict[str, str]
    ranking: ReviewRanking


CacheKey = tuple[Path, str, date]
_cache: OrderedDict[CacheKey, CachedRanking] = OrderedDict()
_cache_lock = Lock()


@dataclass(frozen=True)
class ScanAlert:
    source_id: int
    rule: str
    reference: datetime
    evidence: set[int]


def _read(path: Path) -> bytes:
    with path.open("rb") as handle:
        raw = handle.read(_MAX_BYTES + 1)
    if not 0 < len(raw) <= _MAX_BYTES:
        raise ValueError("invalid file size")
    return raw


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _rows(raw: bytes, *fields: str) -> Iterator[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
    names = reader.fieldnames or []
    if len(set(names)) != len(names) or not set(fields) <= set(names):
        raise ValueError("missing or duplicate columns")
    for row in reader:
        if None in row or None in row.values():
            raise ValueError("malformed row")
        yield row


def _score(raw: str) -> float:
    value = float(raw)
    if not isfinite(value) or not 0 <= value <= 1:
        raise ValueError("invalid score")
    return value


def _timestamp(raw: str) -> datetime:
    value = datetime.fromisoformat(raw)
    if value.tzinfo is not None:
        raise ValueError("scan timestamps must use the source clock")
    return value


def _scan(files: dict[str, bytes], scan_date: date) -> tuple[dict[str, ScanAlert], dict[int, datetime]]:
    alerts = {}
    source_ids = set()
    alert_no_pattern = f"ALT-{scan_date:%Y%m%d}-{_ALERT_NO_SUFFIX_PATTERN}"
    for row in _rows(
        files["alerts.csv"], "alert_no", "alert_id", "rule_id", "reference_ts", "transaction_ids"
    ):
        aid, source_id = row["alert_no"], int(row["alert_id"])
        evidence = [int(uid) for uid in row["transaction_ids"].split()]
        if (
            not re.fullmatch(alert_no_pattern, aid)
            or aid in alerts
            or source_id <= 0
            or source_id in source_ids
            or not row["rule_id"]
            or len(alerts) >= _MAX_ALERTS
            or not evidence
            or len(set(evidence)) != len(evidence)
            or any(uid <= 0 for uid in evidence)
        ):
            raise SnapshotInvalid("ID_MISMATCH")
        source_ids.add(source_id)
        alerts[aid] = ScanAlert(source_id, row["rule_id"], _timestamp(row["reference_ts"]), set(evidence))

    seen = set()
    times: dict[int, datetime] = {}
    for row in _rows(
        files["evidence_transactions.csv"], "alert_no", "alert_id", "rule_id", "transaction_id", "ts"
    ):
        aid, uid = row["alert_no"], int(row["transaction_id"])
        if aid not in alerts:
            raise SnapshotInvalid("ID_MISMATCH")
        alert = alerts[aid]
        ts = _timestamp(row["ts"])
        if (
            (aid, uid) in seen
            or uid not in alert.evidence
            or int(row["alert_id"]) != alert.source_id
            or row["rule_id"] != alert.rule
            or times.setdefault(uid, ts) != ts
        ):
            raise SnapshotInvalid("ID_MISMATCH")
        seen.add((aid, uid))
    if not alerts or len(seen) != sum(len(a.evidence) for a in alerts.values()):
        raise SnapshotInvalid("ID_MISMATCH")
    return alerts, times


def _ml_scores(raw: bytes, alerts: dict[str, ScanAlert]) -> dict[str, tuple[float | None, str | None]]:
    scores = {}
    for row in _rows(raw, "alert_no", "alert_id", "rule_id", "score", "failure_code"):
        aid = row["alert_no"]
        if aid not in alerts:
            raise SnapshotInvalid("ID_MISMATCH")
        alert = alerts[aid]
        if aid in scores or int(row["alert_id"]) != alert.source_id or row["rule_id"] != alert.rule:
            raise SnapshotInvalid("ID_MISMATCH")
        failure = row["failure_code"] or None
        value = _score(row["score"]) if row["score"] else None
        if (value is None) != (failure is not None):
            raise ValueError("invalid ML success/failure record")
        scores[aid] = value, failure
    if scores.keys() != alerts.keys():
        raise SnapshotInvalid("ID_MISMATCH")
    return scores


def _dl_scores(
    files: dict[str, bytes], times: dict[int, datetime]
) -> tuple[dict[int, tuple[int, float]], dict[int, tuple[str, int]]]:
    mapping = {}
    source_keys = set()
    for row in _rows(files["evidence_source_map.csv"], "transaction_id", "source_file", "source_row_number"):
        uid = int(row["transaction_id"])
        key = row["source_file"], int(row["source_row_number"])
        if uid in mapping or key in source_keys or not key[0] or key[1] <= 0:
            raise SnapshotInvalid("ID_MISMATCH")
        source_keys.add(key)
        mapping[uid] = key
    if mapping.keys() != times.keys():
        raise SnapshotInvalid("ID_MISMATCH")
    scores = {}
    for row in _rows(
        files["dl.csv"],
        "transaction_id",
        "source_file",
        "source_row_number",
        "minute_since_2022_09_01",
        "score",
    ):
        uid = int(row["transaction_id"])
        minute = int(row["minute_since_2022_09_01"])
        if (
            uid in scores
            or uid not in mapping
            or mapping[uid] != (row["source_file"], int(row["source_row_number"]))
            or minute != (times[uid] - _EPOCH) // _ONE_MINUTE
        ):
            raise SnapshotInvalid("ID_MISMATCH")
        scores[uid] = minute, _score(row["score"])
    return scores, mapping


def _average_ranks(values: dict[str, float]) -> dict[str, float]:
    ranks = {}
    first = 1
    for _, tied in groupby(sorted(values, key=values.__getitem__), key=values.__getitem__):
        ids = list(tied)
        ranks.update(dict.fromkeys(ids, first + (len(ids) - 1) / 2))
        first += len(ids)
    return ranks


def _rank(scan_date: date, digest: str, files: dict[str, bytes]) -> ReviewRanking:
    alerts, times = _scan(files, scan_date)
    ml = _ml_scores(files["ml.csv"], alerts)
    dl, mapping = _dl_scores(files, times)
    ml_meta, dl_meta, worker_input = (
        json.loads(files[name]) for name in ("ml-summary.json", "dl-summary.json", "worker-input.json")
    )
    scan_hashes = ml_meta["input_sha256"]
    if (
        ml_meta["status"] != "PASS"
        or ml_meta["package"] != "0.1.0rc3"
        or ml_meta["model"] != _ML_MODEL
        or ml_meta["feature_version"] != _ML_FEATURES
        or ml_meta["alerts"] != len(alerts)
        or ml_meta["scored"] != sum(v is not None for v, _ in ml.values())
        or dl_meta["status"] not in {"PASS", "PARTIAL"}
        or dl_meta["mode"] != "full"
        or dl_meta["dl_commit"] != _DL_COMMIT
        or dl_meta["model"] != _DL_MODEL
        or dl_meta["snapshot_manifest_sha256"] != _digest(files["worker-input.json"])
        or dl_meta["snapshot_alerts"] != len(alerts)
        or dl_meta["snapshot_transactions"] != len(times)
        or dl_meta["transactions"] != len(dl)
        or (dl_meta["status"] == "PASS" and len(dl) != len(times))
        or any(scan_hashes[name] != worker_input[f"scan/{name}"] for name in _SCAN_FILES)
        or worker_input["scan/alerts.csv"] != _digest(files["alerts.csv"])
        or worker_input["scan/evidence_transactions.csv"] != _digest(files["evidence_transactions.csv"])
        or worker_input["history/evidence_source_map.csv"] != _digest(files["evidence_source_map.csv"])
    ):
        raise SnapshotInvalid("PROVENANCE_MISMATCH")

    dl_by_alert = {}
    counts = {}
    for aid, alert in alerts.items():
        cutoff = (alert.reference - _EPOCH) // _ONE_MINUTE
        valid = [dl[uid][1] for uid in alert.evidence if uid in dl and dl[uid][0] < cutoff]
        counts[aid] = len(valid)
        if valid and len(valid) == len(alert.evidence):
            dl_by_alert[aid] = max(valid)

    ml_values = {aid: score for aid, (score, _) in ml.items() if score is not None}
    baseline = sorted(ml_values, key=lambda aid: (-ml_values[aid], aid))
    slots = [i for i, aid in enumerate(baseline) if aid in dl_by_alert]
    complete = {baseline[i]: dl_by_alert[baseline[i]] for i in slots}
    ml_ranks = _average_ranks({aid: ml_values[aid] for aid in complete})
    dl_ranks = _average_ranks(complete)
    order = sorted(complete, key=lambda aid: (-max(ml_ranks[aid], dl_ranks[aid]), aid))
    fused = baseline.copy()
    for slot, aid in zip(slots, order, strict=True):
        fused[slot] = aid
    base_position = {aid: pos for pos, aid in enumerate(baseline, 1)}
    fused_position = {aid: pos for pos, aid in enumerate(fused, 1)}
    return ReviewRanking(
        scan_date=scan_date,
        snapshot_sha256=digest,
        ml_model=_ML_MODEL,
        dl_model=_DL_MODEL,
        evidence_transactions=len(times),
        scored_transactions=len(dl),
        linked_alerts=len(complete),
        ml_only_alerts=len(baseline) - len(complete),
        unscored_alerts=len(alerts) - len(baseline),
        alerts=[
            RankedAlert(
                alert_id=aid,
                rule_id=alerts[aid].rule,
                ml_score=ml[aid][0],
                ml_failure_code=ml[aid][1],
                dl_score=dl_by_alert.get(aid),
                evidence_count=len(alerts[aid].evidence),
                dl_linked=counts[aid],
                fallback_reason=(
                    "ML_UNSCORED"
                    if aid not in ml_values
                    else "INCOMPLETE_DL_EVIDENCE"
                    if aid not in complete
                    else None
                ),
                ml_rank=base_position.get(aid),
                fused_rank=fused_position.get(aid),
                reference_ts=reference_text(alerts[aid].reference),
                evidence_digest=evidence_digest(mapping[uid] for uid in alerts[aid].evidence),
            )
            for aid in fused + sorted(alerts.keys() - ml_values.keys())
        ],
    )


def _verified_read(path: Path, expected_sha256: str) -> bytes:
    raw = _read(path)
    if not hmac.compare_digest(_digest(raw), expected_sha256):
        raise SnapshotInvalid("HASH_MISMATCH")
    return raw


def _cached(key: CacheKey) -> CachedRanking | None:
    with _cache_lock:
        entry = _cache.get(key)
        if entry is not None:
            _cache.move_to_end(key)
        return entry


def _remember(key: CacheKey, entry: CachedRanking) -> None:
    with _cache_lock:
        _cache[key] = entry
        _cache.move_to_end(key)
        if len(_cache) > _MAX_CACHE_ENTRIES:
            _cache.popitem(last=False)


def _load(key: CacheKey) -> ReviewRanking:
    path, expected_sha256, scan_date = key
    raw = _verified_read(path, expected_sha256)
    cached = _cached(key)
    if cached is not None:
        # 해시를 다시 검사해 파일 교체나 수정 시각을 원복한 변경도 감지한다.
        for name, digest in cached.hashes.items():
            _verified_read(path.parent / name, digest)
        return cached.ranking

    manifest = json.loads(raw)
    if manifest["scan_date"] != scan_date.isoformat():
        raise SnapshotInvalid("SCAN_MISMATCH")
    hashes = manifest["files"]
    if not isinstance(hashes, dict) or set(hashes) != SNAPSHOT_FILES:
        raise SnapshotInvalid("INVALID_SNAPSHOT")
    files = {name: _verified_read(path.parent / name, digest) for name, digest in hashes.items()}
    ranking = _rank(scan_date, expected_sha256, files)
    _remember(key, CachedRanking(hashes, ranking))
    return ranking


def load_review_ranking(scan_date: date, manifest_path: str, expected_sha256: str) -> ReviewRanking:
    """스캔 전체의 조사 순위를 읽고 검증한다."""
    key = Path(manifest_path), expected_sha256.lower(), scan_date
    try:
        if not manifest_path or not expected_sha256:
            raise SnapshotInvalid("SETTINGS_MISSING")
        return _load(key)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, csv.Error) as exc:
        with _cache_lock:
            _cache.pop(key, None)
        if isinstance(exc, SnapshotInvalid):
            reason = exc.reason
        elif isinstance(exc, FileNotFoundError):
            reason = "FILE_MISSING"
        elif isinstance(exc, OSError):
            reason = "FILE_READ_ERROR"
        else:
            reason = "INVALID_SNAPSHOT"
        raise RankingUnavailable(
            "DL 조사 순위 스냅샷을 사용할 수 없습니다.",
            reason_code=reason,
            error_type=type(exc).__name__,
        ) from None
