"""
Vaccination / certificate list PDF export: chunked queries, optional ID cache, async jobs.

PDF layout matches legacy export_certificates_pdf (single ReportLab Table, four columns).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional, Tuple

from django.core.cache import cache
from django.db import close_old_connections
from django.db.models import Q

from .models import DogRegistration

logger = logging.getLogger(__name__)

try:
    from reportlab.platypus import SimpleDocTemplate, Table
except ImportError:  # pragma: no cover
    SimpleDocTemplate = Table = None  # type: ignore

RowTuple = Tuple[str, str, str, Any]  # reg_no, pet, owner, date_registered

CHUNK_SIZE = 500
ORDERED_IDS_CACHE_TTL = 300
ORDERED_IDS_CACHE_KEY = "dogadopt:cert_pdf:ordered_registration_ids"
JOB_CACHE_KEY_PREFIX = "dogadopt:cert_pdf_job:"
JOB_META_TTL_SECONDS = 600
JOB_MAX_RUN_SECONDS = 480
MAX_CACHED_ID_LIST = 50_000


def _require_reportlab():
    if SimpleDocTemplate is None or Table is None:
        raise RuntimeError("reportlab is required for PDF export.")


def invalidate_vaccination_certificate_export_cache() -> None:
    """Drop cached ordered registration PK lists (call from model signals when export data changes)."""
    cache.delete(ORDERED_IDS_CACHE_KEY)


def _job_cache_key(job_id: str) -> str:
    return f"{JOB_CACHE_KEY_PREFIX}{job_id}"


def _get_job(job_id: str) -> Optional[Dict[str, Any]]:
    return cache.get(_job_cache_key(job_id))


def _set_job(job_id: str, payload: Dict[str, Any]) -> None:
    cache.set(_job_cache_key(job_id), payload, JOB_META_TTL_SECONDS)


def iter_registration_export_rows_chunked() -> Iterator[List[RowTuple]]:
    """
    Yield chunks of rows (reg_no, name_of_pet, owner_name, date_registered)
    in -date_registered order using keyset pagination (<= CHUNK_SIZE rows per query).
    """
    last_dt = None
    last_id: Optional[int] = None
    while True:
        qs = DogRegistration.objects.order_by("-date_registered", "-id")
        if last_dt is not None and last_id is not None:
            qs = qs.filter(
                Q(date_registered__lt=last_dt)
                | (Q(date_registered=last_dt) & Q(pk__lt=last_id))
            )
        batch = list(
            qs[:CHUNK_SIZE].values_list(
                "reg_no", "name_of_pet", "owner_name", "date_registered", "id"
            )
        )
        if not batch:
            break
        yield [row[:4] for row in batch]
        last_dt, last_id = batch[-1][3], batch[-1][4]


def iter_rows_for_cached_ids(ordered_ids: List[int]) -> Iterator[List[RowTuple]]:
    """Replay export order using a cached PK list (chunked ORM reads)."""
    for i in range(0, len(ordered_ids), CHUNK_SIZE):
        chunk_ids = ordered_ids[i : i + CHUNK_SIZE]
        rows = DogRegistration.objects.filter(pk__in=chunk_ids).values_list(
            "reg_no", "name_of_pet", "owner_name", "date_registered", "id"
        )
        by_id = {row[4]: tuple(row[:4]) for row in rows}
        chunk_rows = [by_id[pk] for pk in chunk_ids if pk in by_id]
        if chunk_rows:
            yield chunk_rows


def _row_iterator_prefer_cache() -> Iterator[List[RowTuple]]:
    cached_ids = cache.get(ORDERED_IDS_CACHE_KEY)
    if isinstance(cached_ids, list) and cached_ids:
        yield from iter_rows_for_cached_ids(cached_ids)
        return
    yield from iter_registration_export_rows_chunked()


def write_registration_certificates_pdf(path: str) -> None:
    """
    Build the legacy certificate export PDF at path (file on disk — not an in-memory buffer).
    """
    _require_reportlab()
    doc = SimpleDocTemplate(path)
    data: List[List[str]] = [["Reg No", "Pet Name", "Owner", "Date Issued"]]
    for chunk in _row_iterator_prefer_cache():
        for reg_no, pet, owner, dt in chunk:
            data.append(
                [
                    reg_no,
                    pet,
                    owner,
                    dt.strftime("%b %d, %Y") if hasattr(dt, "strftime") else str(dt),
                ]
            )
    table = Table(data)
    doc.build([table])


def refresh_ordered_id_cache_if_needed() -> None:
    """Populate ordered PK cache when empty (ORDERED_IDS_CACHE_TTL seconds)."""
    if cache.get(ORDERED_IDS_CACHE_KEY) is not None:
        return
    ids = list(
        DogRegistration.objects.order_by("-date_registered", "-id").values_list(
            "id", flat=True
        )
    )
    if len(ids) <= MAX_CACHED_ID_LIST:
        cache.set(ORDERED_IDS_CACHE_KEY, ids, ORDERED_IDS_CACHE_TTL)


class VaccinationListPrintService:
    """Chunked queries, cache-friendly iteration, and PDF generation (legacy table layout)."""

    CHUNK_SIZE = CHUNK_SIZE

    write_registration_pdf = staticmethod(write_registration_certificates_pdf)
    refresh_id_cache = staticmethod(refresh_ordered_id_cache_if_needed)
    invalidate_export_cache = staticmethod(invalidate_vaccination_certificate_export_cache)
    iter_export_row_chunks = staticmethod(iter_registration_export_rows_chunked)


class VaccinationCertificatePdfJob:
    """Async PDF job: run in a background thread; state stored in Django cache."""

    __slots__ = ("job_id", "user_id")

    def __init__(self, job_id: str, user_id: int):
        self.job_id = job_id
        self.user_id = user_id

    @classmethod
    def dispatch(cls, user_id: int) -> "VaccinationCertificatePdfJob":
        job_id = str(uuid.uuid4())
        now = time.time()
        instance = cls(job_id, user_id)
        _set_job(
            job_id,
            {
                "status": "pending",
                "user_id": user_id,
                "created_at": now,
                "started_at": None,
                "path": None,
                "error": None,
            },
        )
        thread = threading.Thread(
            target=instance._run_worker,
            name=f"cert-pdf-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return instance

    def _run_worker(self) -> None:
        close_old_connections()
        path = None
        try:
            job = _get_job(self.job_id) or {}
            job["status"] = "running"
            job["started_at"] = time.time()
            _set_job(self.job_id, job)

            VaccinationListPrintService.refresh_id_cache()

            fd, path = tempfile.mkstemp(suffix=".pdf", prefix="cert_export_")
            os.close(fd)
            VaccinationListPrintService.write_registration_pdf(path)

            job = _get_job(self.job_id) or {}
            job["status"] = "done"
            job["path"] = path
            job["error"] = None
            _set_job(self.job_id, job)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Certificate PDF job %s failed", self.job_id)
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
            job = _get_job(self.job_id) or {}
            job["status"] = "failed"
            job["path"] = None
            job["error"] = str(exc)
            _set_job(self.job_id, job)
        finally:
            close_old_connections()


def get_job_status_payload(job_id: str, download_path_name: str) -> Optional[Dict[str, Any]]:
    job = _get_job(job_id)
    if job is None:
        return None
    now = time.time()
    started = job.get("started_at")
    created = job.get("created_at")
    ref_time = started or created
    if job.get("status") in {"pending", "running"} and ref_time and (
        now - float(ref_time) > JOB_MAX_RUN_SECONDS
    ):
        job["status"] = "timeout"
        job["error"] = job.get("error") or "Job exceeded maximum run time."
        if job.get("path") and os.path.exists(job["path"]):
            try:
                os.unlink(job["path"])
            except OSError:
                pass
        job["path"] = None
        _set_job(job_id, job)

    status = job.get("status", "unknown")
    download_url = None
    if status == "done" and job.get("path"):
        download_url = download_path_name

    return {
        "job_id": job_id,
        "status": status,
        "download_url": download_url,
        "error": job.get("error"),
    }


def pop_job_file_path(job_id: str, user_id: int) -> Optional[str]:
    """Return temp path for download if job is done and owned by user; caller must delete file after streaming."""
    job = _get_job(job_id)
    if not job or int(job.get("user_id", -1)) != int(user_id):
        return None
    if job.get("status") != "done":
        return None
    path = job.get("path")
    if not path or not os.path.isfile(path):
        return None
    job["path"] = None
    job["status"] = "downloaded"
    _set_job(job_id, job)
    return path


def vaccination_certificate_export_job_json(job_id: str) -> Dict[str, Any]:
    """Build status JSON with resolved download URL."""
    from django.urls import reverse

    base = get_job_status_payload(
        job_id,
        reverse(
            "dogadoption_admin:export_certificates_pdf_job_download",
            kwargs={"job_id": job_id},
        ),
    )
    if base is None:
        return {
            "job_id": job_id,
            "status": "missing",
            "download_url": None,
            "error": "Unknown or expired job.",
        }
    return base
