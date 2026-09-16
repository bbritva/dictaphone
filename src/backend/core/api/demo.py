"""Demo-only endpoints for the transcript-quality demo page.

Scope
-----
These endpoints exist to feed the `/demo` page and nothing else. They proxy to
the summary service's own demo route (`/api/v2/demo/transcript-quality/...`),
which runs the two transcript-quality stages on a transcript handed to it
directly.

The proxy is here for one reason: `AI_SERVICE_API_KEY` is a server-side secret
and must not reach the browser. Nothing else is added -- the summary service's
JSON is passed through untouched, so the page shows what the pipeline actually
returned.

Two ways in
-----------
`run_transcript_quality_demo` is the `/demo` page: the transcript is uploaded
by the user, and no stored object is involved at all.

`run_transcript_quality_demo_on_job` is the panel on the recording page: the
transcript is the one Dictaphone already holds for an existing `AiFileJob`, so
a glossary and an attendee list can be tried against a real recording. It reads
the stored JSON and forwards it under the same `transcript` field, which is why
the summary service needs no change to serve both.

What this does NOT touch
------------------------
No write, ever. Nothing here creates, updates or deletes a `File` or an
`AiFileJob`, and nothing is written back to storage. The job-backed route opens
the stored transcript read-only and hands the bytes to the summary service; the
corrected transcript exists only in the response the browser receives. The
normal audio ingestion path (upload -> extract audio -> transcribe -> webhook)
is not involved and is not changed.
"""

import logging

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404

import requests as requests_lib
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import AiFileJob, AiJobStatusChoices, AiJobTypeChoices
from core.storage import get_storage_for_file

logger = logging.getLogger(__name__)

#: The demo runs two LLM stages over a whole transcript. A cached run answers
#: in under a second; a cold one waits on the model.
DEMO_TIMEOUT_SECONDS = 300

#: Nothing in this demo needs a large file, and the three uploads are read into
#: memory before being forwarded.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: The three drop zones, and whether the page may run without one.
UPLOAD_FIELDS = (("transcript", True), ("glossary", False), ("calendar", False))


def _summary_service_url(path):
    """Build a URL on the summary service from its configured base."""
    return settings.AI_SERVICE_URL + path


def _forward(response):
    """Turn the summary service's reply into this API's reply.

    The body is passed through as-is so the page reports the pipeline's own
    numbers and the pipeline's own error messages, not a rewritten version.
    """
    try:
        payload = response.json()
    except ValueError:
        logger.error(
            "Summary demo route returned a non-JSON body (HTTP %s)",
            response.status_code,
        )
        return Response(
            {"error": f"Le service de résumé a répondu en HTTP {response.status_code} "
                      "sans corps JSON."},
            status=status.HTTP_502_BAD_GATEWAY,
        )
    return Response(payload, status=response.status_code)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def run_transcript_quality_demo(request):
    """Forward the three dropped files to the summary service and return its report.

    The transcript is required; the glossary and the calendar are optional, so
    the page can show what each one contributes by leaving it out.
    """
    files = {}
    for field, required in UPLOAD_FIELDS:
        upload = request.FILES.get(field)
        if upload is None:
            if required:
                return Response(
                    {"error": f"Le fichier « {field} » est obligatoire."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            continue
        if upload.size > MAX_UPLOAD_BYTES:
            return Response(
                {
                    "error": f"« {upload.name} » dépasse la taille maximale "
                             f"({MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        files[field] = (upload.name, upload.read(), upload.content_type)

    try:
        response = requests_lib.post(
            _summary_service_url("demo/transcript-quality/run"),
            files=files,
            headers={"Authorization": f"Bearer {settings.AI_SERVICE_API_KEY}"},
            timeout=DEMO_TIMEOUT_SECONDS,
        )
    except requests_lib.RequestException as exc:
        logger.error("Transcript-quality demo run failed: %s", exc)
        return Response(
            {"error": f"Le service de résumé est injoignable : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return _forward(response)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def publish_transcript_quality_demo(request):
    """Push one already-computed run to Docs.

    Deliberately a separate call: a run must never publish on its own, or a
    demo session leaves a document in Docs per click.
    """
    run_id = request.data.get("run_id")
    if not run_id:
        return Response(
            {"error": "« run_id » est obligatoire : lancez d'abord une correction."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    body = {"run_id": run_id, "which": request.data.get("which", "after")}
    title = request.data.get("title")
    if title:
        body["title"] = title

    try:
        response = requests_lib.post(
            _summary_service_url("demo/transcript-quality/publish"),
            json=body,
            headers={"Authorization": f"Bearer {settings.AI_SERVICE_API_KEY}"},
            timeout=DEMO_TIMEOUT_SECONDS,
        )
    except requests_lib.RequestException as exc:
        logger.error("Transcript-quality demo publish failed: %s", exc)
        return Response(
            {"error": f"Le service de résumé est injoignable : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return _forward(response)


def _read_uploaded_side_files(request):
    """Read the glossary and the calendar off the request, if they were sent.

    Both are optional here: the transcript comes from the stored job, so a run
    with neither is still meaningful -- it shows what the service's own shipped
    glossary does on its own.

    Returns:
        A `(files, error_response)` pair. `error_response` is None on success.
    """
    files = {}
    for field in ("glossary", "calendar"):
        upload = request.FILES.get(field)
        if upload is None:
            continue
        if upload.size > MAX_UPLOAD_BYTES:
            return None, Response(
                {
                    "error": f"« {upload.name} » dépasse la taille maximale "
                             f"({MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        files[field] = (upload.name, upload.read(), upload.content_type)
    return files, None


def _stored_transcript_of(ai_job):
    """Read one AI job's stored transcript out of object storage, read-only.

    The file is opened for reading and closed; nothing is written back, and the
    `AiFileJob` row is not touched. What the summary service returns is a new
    transcript computed in memory, never a replacement for this one.

    Raises:
        Http404: the job is not a finished transcript.
    """
    if ai_job.type != AiJobTypeChoices.TRANSCRIPT:
        raise Http404("This AI job is not a transcript.")
    if ai_job.status != AiJobStatusChoices.SUCCESS:
        raise Http404("This transcript is not finished.")

    with get_storage_for_file(ai_job.file).open(ai_job.key, "rb") as stored:
        return stored.read()


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def run_transcript_quality_demo_on_job(request, pk):
    """Re-run the correction stages over a transcript Dictaphone already holds.

    Same work as `run_transcript_quality_demo`, sourced differently: instead of
    a transcript posted by the browser, the transcript is the one stored for
    `pk`. The glossary and the attendee list are still uploads, because trying
    different ones against the same recording is the whole point of the panel.

    The response is the summary service's report, unchanged. Nothing is saved.
    """
    ai_job = get_object_or_404(
        AiFileJob.objects.select_related("file", "file__creator"), pk=pk
    )
    # Same rule as `AiJobPermission`: a job is only visible to the creator of
    # the file it belongs to, and never once that file is hard-deleted.
    if ai_job.file.hard_deleted_at is not None:
        raise Http404("This recording no longer exists.")
    if ai_job.file.creator != request.user:
        raise Http404("This recording does not belong to you.")

    files, error = _read_uploaded_side_files(request)
    if error is not None:
        return error

    try:
        transcript = _stored_transcript_of(ai_job)
    except Http404:
        raise
    except OSError as exc:
        logger.error("Could not read the stored transcript of %s: %s", ai_job.id, exc)
        return Response(
            {"error": f"Le transcript enregistré est illisible : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # No size cap on this side. The cap above protects the service from a large
    # *upload*; this transcript is one Dictaphone produced itself, and refusing
    # to read it back would only hide long recordings from the panel.
    files["transcript"] = (
        f"{ai_job.id}.json",
        transcript,
        "application/json",
    )

    try:
        response = requests_lib.post(
            _summary_service_url("demo/transcript-quality/run"),
            files=files,
            headers={"Authorization": f"Bearer {settings.AI_SERVICE_API_KEY}"},
            timeout=DEMO_TIMEOUT_SECONDS,
        )
    except requests_lib.RequestException as exc:
        logger.error("Transcript-quality rerun failed for job %s: %s", ai_job.id, exc)
        return Response(
            {"error": f"Le service de résumé est injoignable : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    return _forward(response)
