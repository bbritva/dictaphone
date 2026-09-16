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

What this does NOT touch
------------------------
No `File`, no `AiFileJob`, no storage, no Celery task. The normal audio
ingestion path (upload -> extract audio -> transcribe -> webhook) is not
involved and is not changed. A transcript dropped here is read, forwarded, and
forgotten.
"""

import logging

from django.conf import settings

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
