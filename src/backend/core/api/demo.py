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

Three ways in
-------------
`run_transcript_quality_demo` is the `/demo` page: the transcript is uploaded
by the user, and no stored object is involved at all.

`run_transcript_quality_demo_on_job` is the panel on the recording page: the
transcript is the one Dictaphone already holds for an existing `AiFileJob`, so
a glossary and an attendee list can be tried against a real recording. It reads
the stored JSON and forwards it under the same `transcript` field, which is why
the summary service needs no change to serve both.

`import_transcript_as_recording` is the third one, and the only one that keeps
anything: the transcript is uploaded like on `/demo`, but the corrected result
is stored as a real recording, so it shows up in the list and opens like any
other. What that costs and how it is done is documented on the function.

What this does NOT touch
------------------------
The first two routes never write: nothing they do creates, updates or deletes
a `File` or an `AiFileJob`, and nothing is written back to storage.

The third one does write, and only through the ordinary models -- a `File` and
one `AiFileJob` of type `transcript`, created the way the audio path creates
them. No model behaviour is overridden and no task is bypassed, because no task
is involved: there is no audio to extract and nothing to transcribe.

The normal audio ingestion path (upload -> extract audio -> transcribe ->
webhook) is not involved in any of the three and is not changed by any of them.
"""

import json
import logging
from os.path import splitext
from time import monotonic, sleep
from urllib.parse import urljoin
from uuid import UUID

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404

import requests as requests_lib
from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError
from rest_framework import status
from rest_framework.decorators import (
    api_view,
    parser_classes,
    permission_classes,
)
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import (
    AiFileJob,
    AiJobStatusChoices,
    AiJobTypeChoices,
    File,
    FileAudioExtractionStateChoices,
    FileLifecycleStateChoices,
    FileSourceChoices,
    FileTypeChoices,
    FileUploadStateChoices,
)
from core.storage import get_storage_bucket_name, get_storage_for_file
from core.tasks.file import push_markdown_to_docs
from core.utils import format_transcript
from core.webhook_models import WhisperXResponse

logger = logging.getLogger(__name__)

#: The demo runs two LLM stages over a whole transcript. A cached run answers
#: in under a second; a cold one waits on the model.
DEMO_TIMEOUT_SECONDS = 300

#: Nothing in this demo needs a large file, and the three uploads are read into
#: memory before being forwarded.
MAX_UPLOAD_BYTES = 5 * 1024 * 1024

#: The three drop zones, and whether the page may run without one.
UPLOAD_FIELDS = (("transcript", True), ("glossary", False), ("calendar", False))

#: How long the import flow waits for the summary service to finish a
#: compte-rendu before giving up on it. The summarisation is one more Albert
#: round trip over the whole transcript, so it is minutes, not seconds -- but
#: it is not unbounded either, or the browser hangs on a dead worker.
SUMMARY_POLL_TIMEOUT_SECONDS = 240

#: Gap between two status polls. Short enough that a cached run answers fast,
#: long enough not to hammer the service.
SUMMARY_POLL_INTERVAL_SECONDS = 3

#: The three documents the import flow pushes to Docs, in the order the modal
#: lists them. `kind` is what the browser keys on; the label is what a failure
#: message names, so "le compte-rendu n'a pas pu..." reads as French.
DOC_RAW = "raw"
DOC_CORRECTED = "corrected"
DOC_SUMMARY = "summary"

#: The document the three hang under in Docs' sidebar tree. It is deliberately
#: not one of the three above: it carries no result, it is never returned in the
#: `documents` list the modal renders, and the browser never keys on it.
DOC_PARENT = "parent"


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


#: The imported recording carries no audio, so there is nothing to play and
#: nothing to download. `original_data_deleted` is the state the product
#: already has for exactly that shape -- `ListFileSerializer.get_url` returns
#: None for it, the recording page hides the player instead of handing it a
#: null `src`, and "relancer la transcription" is disabled because there is no
#: audio to transcribe again. Reusing it is what keeps this route from needing
#: a new state, a new serializer branch, or a change to the audio path.
#:
#: The one thing it gets wrong is the wording: the page says "fichier conservé
#: jusqu'au ..." rather than "audio conservé jusqu'au ...", which reads as "the
#: audio was deleted" when the truth is "there never was any". `source` carries
#: that truth: see `FileSourceChoices.IMPORTED_TRANSCRIPT`.
IMPORTED_LIFECYCLE_STATE = FileLifecycleStateChoices.ORIGINAL_DATA_DELETED


def _duration_of(transcript: WhisperXResponse) -> float:
    """Return the last timestamp in the transcript, in seconds.

    `File.duration_seconds` is not nullable and the list shows it, so it has to
    be something. The end of the last timed segment is the honest answer: it is
    how long the conversation this transcript describes ran, measured from the
    transcript itself rather than invented.
    """
    ends = [segment.end for segment in transcript.segments if segment.end is not None]
    return float(max(ends)) if ends else 0.0


def _corrected_transcript_of(payload):
    """Pull the corrected WhisperX transcript out of a summary-service report.

    The report is the summary service's, so this validates it against
    Dictaphone's own `WhisperXResponse` before anything is stored. Getting this
    wrong is invisible at write time and fatal at read time: `to_markdown` and
    the transcript proxy both re-validate, so a transcript that does not fit
    would store fine and then break "Ouvrir dans Docs" and the recording page.

    Returns:
        A `(transcript, raw, error_response)` triple. `error_response` is None
        on success.
    """
    after = payload.get("after") or {}
    raw = after.get("transcript")
    if raw is None:
        return (
            None,
            None,
            Response(
                {
                    "error": "Le service de résumé n'a pas renvoyé le transcript "
                    "corrigé (champ « after.transcript »). Version trop "
                    "ancienne du service ?"
                },
                status=status.HTTP_502_BAD_GATEWAY,
            ),
        )
    try:
        transcript = WhisperXResponse.model_validate(raw)
    except ValidationError as exc:
        logger.error("Corrected transcript does not validate: %s", exc)
        return (
            None,
            None,
            Response(
                {
                    "error": "Le transcript corrigé renvoyé par le service de "
                    f"résumé n'a pas la forme attendue : {str(exc)[:300]}"
                },
                status=status.HTTP_502_BAD_GATEWAY,
            ),
        )
    return transcript, raw, None


def _create_imported_recording(user, *, title, filename, transcript, language):
    """Create the `File` a corrected transcript is attached to.

    Written through the ordinary model, in the ordinary order, so every
    invariant `File.save` enforces still runs: the configuration snapshot, the
    storage bucket, the deletion deadlines. The three state fields are set on a
    second save because the first one forces `pending` on any new file -- that
    rule is the audio path's and it is left alone.
    """
    file = File(
        type=FileTypeChoices.AUDIO_RECORDING,
        title=title,
        creator=user,
        filename=filename,
        duration_seconds=_duration_of(transcript),
        mimetype="application/json",
        language=language,
        source=FileSourceChoices.IMPORTED_TRANSCRIPT,
    )
    file.save()

    # `ready` is what the list filters on, and it is true: there is nothing
    # still uploading. `extraction_done` is what the recording page reads to
    # decide whether to keep saying "extraction en cours"; there is no audio,
    # so the extraction is as done as it will ever be.
    file.upload_state = FileUploadStateChoices.READY
    file.audio_extraction_state = FileAudioExtractionStateChoices.EXTRACTION_DONE
    file.lifecycle_state = IMPORTED_LIFECYCLE_STATE
    file.save(
        update_fields=["upload_state", "audio_extraction_state", "lifecycle_state"]
    )
    return file


def _docs_browser_url(docs_app_id):
    """The link a human clicks, built the way the recording page builds it."""
    return urljoin(settings.DOCS_BASE_URL, f"docs/{docs_app_id}/")


def _parent_id_of(request):
    """Read the optional Docs parent id a client sends back on a later call.

    The import creates the parent and hands its id to the browser; nothing on
    the server stores it. A client that has it sends it back, a client that
    never had it -- an older one, or one summarising an import from another
    session -- leaves the field out, and gets the root document it has always
    got.

    Only the shape is checked. The id names a document in Docs, not one of ours,
    and Docs refuses any parent the named user is not owner or admin of, so a
    tampered value cannot reach a document the caller has no rights on.

    Returns:
        A `(parent_id, error_response)` pair; at most one is set. Both are None
        when the field was not sent, which is the supported old call.
    """
    raw = request.data.get("parent_document_id")
    if raw is None:
        return None, None

    try:
        return str(UUID(str(raw))), None
    except (AttributeError, TypeError, ValueError):
        return None, Response(
            {"error": "« parent_document_id » n'est pas un identifiant de document valide."},
            status=status.HTTP_400_BAD_REQUEST,
        )


def _push_document(
    creator, *, kind, label, title, markdown, log_subject=None, parent_id=None
):
    """Push one markdown to Docs and describe what happened, win or lose.

    Fails soft on purpose: the import creates three documents and the three are
    independent. One of them failing must not cost the caller the other two, so
    every outcome -- published, nothing to publish, Docs refused, Docs too slow
    -- comes back as a row the modal can show, and never as an exception that
    unwinds the whole import.

    `parent_id` files the document under an existing Docs document instead of
    creating another root. `None` is the old behaviour, and stays the fallback
    when the parent itself could not be created.

    Returns:
        A dict with `kind`, `title`, `url` and `error`. Exactly one of `url`
        and `error` is set, so an empty stage cannot be shown as a success.
    """
    row = {"kind": kind, "title": title, "url": None, "docs_app_id": None, "error": None}

    if not (markdown or "").strip():
        row["error"] = (
            f"{label} : le service de résumé n'a renvoyé aucun contenu à publier."
        )
        return row

    try:
        docs_app_id = push_markdown_to_docs(
            title=title,
            content=markdown,
            creator=creator,
            log_subject=log_subject,
            parent_id=parent_id,
            # Three documents for one import would be three e-mails. The modal
            # hands back the three links directly, so the mail adds nothing.
            send_notification_email=False,
        )
    except requests_lib.RequestException as exc:
        logger.error("Pushing « %s » to Docs failed: %s", title, exc)
        row["error"] = f"{label} : la publication dans Docs a échoué ({exc})."
        return row

    if docs_app_id is None:
        row["error"] = (
            f"{label} : Docs n'a pas répondu à temps. Le document a peut-être "
            "été créé, mais son lien est perdu."
        )
        return row

    row["docs_app_id"] = docs_app_id
    row["url"] = _docs_browser_url(docs_app_id)
    return row


@api_view(["POST"])
@permission_classes([IsAuthenticated])
@parser_classes([MultiPartParser])
def import_transcript_as_recording(  # noqa: PLR0911  pylint: disable=too-many-return-statements
    request,
):
    """Correct a transcript handed to us, and keep the result as a recording.

    Same three uploads as `/demo`, same single call to the summary service. The
    difference is what happens to the answer: instead of being rendered once on
    a page and thrown away, the corrected transcript is stored as the
    `AiFileJob` of a new `File`, so it lands in `/recordings` and opens like
    anything else.

    No audio exists anywhere in this flow. The route creates no upload, queues
    no task and calls no transcription: the transcript is the input, so every
    stage before the correction has already happened elsewhere.

    The full report is returned alongside the new file, because the numbers it
    carries -- what was flagged, what was corrected, and why nothing was when
    nothing was -- are exactly as relevant here as on `/demo`, and are gone
    once the response is discarded.
    """
    upload = request.FILES.get("transcript")
    if upload is None:
        return Response(
            {"error": "Le fichier « transcript » est obligatoire."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if upload.size > MAX_UPLOAD_BYTES:
        return Response(
            {
                "error": f"« {upload.name} » dépasse la taille maximale "
                f"({MAX_UPLOAD_BYTES // (1024 * 1024)} Mo)."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    files, error = _read_uploaded_side_files(request)
    if error is not None:
        return error
    files["transcript"] = (upload.name, upload.read(), upload.content_type)

    language = request.data.get("language") or "fr"

    try:
        response = requests_lib.post(
            _summary_service_url("demo/transcript-quality/run"),
            files=files,
            headers={"Authorization": f"Bearer {settings.AI_SERVICE_API_KEY}"},
            timeout=DEMO_TIMEOUT_SECONDS,
        )
    except requests_lib.RequestException as exc:
        logger.error("Transcript import run failed: %s", exc)
        return Response(
            {"error": f"Le service de résumé est injoignable : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    # A refused or failed run is reported exactly as `/demo` reports it, and
    # nothing is created: a recording is only worth keeping if the correction
    # actually ran.
    if not response.ok:
        return _forward(response)
    try:
        payload = response.json()
    except ValueError:
        return _forward(response)

    transcript, raw, error = _corrected_transcript_of(payload)
    if error is not None:
        return error

    title = (request.data.get("title") or "").strip()
    if not title:
        title = splitext(upload.name)[0] or "Transcript importé"

    file = _create_imported_recording(
        request.user,
        title=title[:255],
        filename=upload.name,
        transcript=transcript,
        language=language,
    )

    # Created pending, not successful: `AiFileJob.key` needs the row's id, so
    # the object cannot exist before the row does. Claiming success before the
    # transcript is readable would put a recording in the list whose transcript
    # 404s.
    ai_job = AiFileJob.objects.create(
        remote_job_id=None,
        file=file,
        type=AiJobTypeChoices.TRANSCRIPT,
        status=AiJobStatusChoices.PENDING,
        language=language,
    )

    content = json.dumps(raw).encode("utf-8")
    storage = get_storage_for_file(file)
    try:
        storage.connection.meta.client.put_object(
            Bucket=get_storage_bucket_name(storage),
            Key=ai_job.key,
            Body=content,
            ContentType="application/json",
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        logger.error("Could not store the imported transcript of %s: %s", file.id, exc)
        ai_job.status = AiJobStatusChoices.FAILED
        ai_job.save(update_fields=["status"])
        return Response(
            {
                "error": "Le transcript corrigé n'a pas pu être enregistré : "
                f"{exc}. L'enregistrement apparaît en échec dans la "
                "liste."
            },
            status=status.HTTP_502_BAD_GATEWAY,
        )

    ai_job.status = AiJobStatusChoices.SUCCESS
    ai_job.save(update_fields=["status"])

    file.size = len(content)
    file.save(update_fields=["size"])

    logger.info(
        "Imported transcript stored as file %s (ai job %s), no audio",
        file.id,
        ai_job.id,
    )

    # ---- the two transcript documents --------------------------------------
    # Both markdowns are already in the answer the summary service just gave
    # us: `before` is the transcript rendered with both correction stages
    # closed -- i.e. the transcript as it was handed in -- and `after` is the
    # corrected one. Nothing is recomputed, and no second call is made.
    #
    # The raw one is pushed straight from here and gets no `AiFileJob`. A
    # second row of type `transcript` on the same file would be a second
    # answer to "what is this recording's transcript", which the recording
    # page, the retry action and `to_markdown` all assume there is one of. The
    # raw text is a demo artefact, not the recording's transcript, so it lives
    # in Docs and nowhere else -- and that needs no new job type and no
    # migration.
    #
    # They are pushed under a parent document rather than as roots. Docs' left
    # sidebar is a tree, and `create-for-owner` used to only ever make roots, so
    # opening one of the documents of an import showed that document and nothing
    # else: the other two were unreachable from it. The parent is what gives the
    # import a tree to be listed in.
    parent = _push_document(
        request.user,
        kind=DOC_PARENT,
        log_subject=file.id,
        label="Dossier de l'import",
        # The recording's own title, unsuffixed: it names the set, the children
        # name what each one is.
        title=file.title[:255],
        markdown=(
            f"# {file.title}\n\n"
            "Les documents produits à partir de cet enregistrement sont "
            "classés sous celui-ci."
        ),
    )
    # Fail-soft, like every other push here: if the parent could not be created
    # the three documents are still published, as roots, exactly as before.
    parent_id = parent["docs_app_id"]

    documents = [
        _push_document(
            request.user,
            kind=DOC_RAW,
            log_subject=file.id,
            label="Transcript brut",
            title=f"{file.title} — transcript brut"[:255],
            markdown=(payload.get("before") or {}).get("markdown"),
            parent_id=parent_id,
        )
    ]

    corrected = _push_document(
        request.user,
        kind=DOC_CORRECTED,
        log_subject=file.id,
        label="Transcript corrigé",
        title=f"{file.title} — transcript corrigé"[:255],
        markdown=(payload.get("after") or {}).get("markdown"),
        parent_id=parent_id,
    )
    # Carried on the job, so "Ouvrir dans Docs" on the recording page opens
    # this very document instead of creating a fourth one.
    if corrected["docs_app_id"]:
        ai_job.docs_app_id = corrected["docs_app_id"]
        ai_job.save(update_fields=["docs_app_id"])
    documents.append(corrected)

    return Response(
        {
            **payload,
            "file": {
                "id": str(file.id),
                "title": file.title,
                "duration_seconds": file.duration_seconds,
                "ai_job_id": str(ai_job.id),
            },
            # The compte-rendu is deliberately absent here: it is another
            # Albert round trip, and making the browser wait for it would hold
            # the two documents that already exist hostage to it. The modal
            # asks for it on the next call.
            "documents": documents,
            # Not a row of `documents`: that list is what the modal renders,
            # one line per result, and the parent carries no result of its own.
            # It is here so the browser can hand it back on the summarize call
            # -- the only way that later request can learn where this import's
            # tree is. None when the parent push failed and the two documents
            # above went to the root instead.
            "parent_document_id": parent_id,
        },
        status=status.HTTP_201_CREATED,
    )


def _summarize_remotely(*, remote_job_id):
    """Wait for one summarize job and return the URL of its result.

    The summary service's summarize route is asynchronous: it answers with a
    job id and, in the audio path, pushes the result back through a webhook
    much later. The import flow has no later -- the browser is waiting on a
    modal -- so it polls the service's own status route instead. Nothing new is
    invented: the job was created the way the audio path creates it, and the
    status route is the one the service already publishes.

    Returns:
        A `(summary_data_url, error_message)` pair; exactly one is None.
    """
    deadline = monotonic() + SUMMARY_POLL_TIMEOUT_SECONDS
    headers = {"Authorization": f"Bearer {settings.AI_SERVICE_API_KEY}"}

    while monotonic() < deadline:
        sleep(SUMMARY_POLL_INTERVAL_SECONDS)
        try:
            poll = requests_lib.get(
                _summary_service_url(f"async-jobs/summarize/{remote_job_id}"),
                headers=headers,
                timeout=30,
            )
        except requests_lib.RequestException as exc:
            logger.error("Polling summary job %s failed: %s", remote_job_id, exc)
            return None, f"Le service de résumé est devenu injoignable : {exc}"

        # The status route reads Redis directly and 404s until the worker has
        # written the task's first state. That is a normal early answer, not a
        # lost job.
        if poll.status_code == status.HTTP_404_NOT_FOUND:
            continue
        if not poll.ok:
            return None, (
                "Le service de résumé a répondu en HTTP "
                f"{poll.status_code} pendant le suivi du compte-rendu."
            )
        try:
            body = poll.json()
        except ValueError:
            return None, "Le suivi du compte-rendu n'a pas renvoyé de JSON."

        if body.get("status") == "success":
            url = body.get("summary_data_url")
            if not url:
                return None, (
                    "Le service de résumé annonce un compte-rendu terminé sans "
                    "en donner l'adresse."
                )
            return url, None
        if body.get("status") == "failure":
            return None, (
                "Le service de résumé a échoué sur le compte-rendu "
                f"({body.get('error_code') or 'raison inconnue'})."
            )

    return None, (
        f"Le compte-rendu n'était toujours pas prêt après "
        f"{SUMMARY_POLL_TIMEOUT_SECONDS // 60} minutes. Les transcripts, eux, "
        "sont bien enregistrés."
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def summarize_imported_recording(  # noqa: PLR0911  pylint: disable=too-many-return-statements
    request, pk
):
    """Summarise an imported recording's corrected transcript, and push it to Docs.

    The second half of the import flow, and a separate call on purpose: the two
    transcript documents exist the moment the correction is done, and must be
    shown then rather than after another minutes-long model call. So the modal
    shows them, then asks for this.

    Only ever runs on a recording the import created (`source` is
    `imported_transcript`). A recording that came from audio already gets its
    compte-rendu from the ordinary pipeline, and nothing here touches that
    path: the job created below is the same `summary` job the audio path
    creates, made with the same request against the same route.

    Takes an optional `parent_document_id` in the body: the Docs document the import
    created for this recording, handed back by the browser because nothing on
    the server remembers it. Omitting it is a supported call, not a degraded
    one -- the compte-rendu is then published as a root document, which is what
    every client did before the field existed.
    """
    ai_job = get_object_or_404(
        AiFileJob.objects.select_related("file", "file__creator"), pk=pk
    )
    file = ai_job.file
    # Same three rules as the rerun panel: a job belongs to the creator of its
    # file, and is gone with it.
    if file.hard_deleted_at is not None:
        raise Http404("This recording no longer exists.")
    if file.creator != request.user:
        raise Http404("This recording does not belong to you.")
    if ai_job.type != AiJobTypeChoices.TRANSCRIPT:
        raise Http404("This AI job is not a transcript.")
    if ai_job.status != AiJobStatusChoices.SUCCESS:
        raise Http404("This transcript is not finished.")

    if file.source != FileSourceChoices.IMPORTED_TRANSCRIPT:
        return Response(
            {
                "error": "Cette route ne sert qu'aux transcripts importés : un "
                "enregistrement audio reçoit son compte-rendu par le "
                "pipeline habituel."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Checked here, before anything is created or any model is called: a
    # malformed value must cost nothing.
    #
    # Shape is all we check. We do not verify that this id is the parent this
    # import actually created, and we do not need to: Docs refuses any parent
    # the named user is not owner or admin of. That is the bound we rely on --
    # the worst a tampered value buys the caller is filing their own
    # compte-rendu under another of their own documents.
    parent_id, error = _parent_id_of(request)
    if error is not None:
        return error

    # A double click must not buy a second document.
    already = (
        AiFileJob.objects.filter(
            file=file,
            type=AiJobTypeChoices.SUMMARIZE,
            status=AiJobStatusChoices.SUCCESS,
            docs_app_id__isnull=False,
        )
        .order_by("-created_at")
        .first()
    )
    if already is not None:
        return Response(
            {
                "document": {
                    "kind": DOC_SUMMARY,
                    "title": f"{file.title} — compte-rendu"[:255],
                    "url": _docs_browser_url(already.docs_app_id),
                    "docs_app_id": already.docs_app_id,
                    "error": None,
                }
            },
            status=status.HTTP_200_OK,
        )

    try:
        stored = _stored_transcript_of(ai_job)
    except OSError as exc:
        logger.error("Could not read the stored transcript of %s: %s", ai_job.id, exc)
        return Response(
            {"error": f"Le transcript enregistré est illisible : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    try:
        transcript = WhisperXResponse.model_validate_json(stored)
    except ValidationError as exc:
        return Response(
            {"error": f"Le transcript enregistré n'a pas la forme attendue : {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )

    summary_job = AiFileJob.objects.create(
        remote_job_id=None,
        file=file,
        type=AiJobTypeChoices.SUMMARIZE,
        status=AiJobStatusChoices.PENDING,
        language=ai_job.language,
    )

    def failed(message, http_status=status.HTTP_502_BAD_GATEWAY):
        """Mark the job failed, then say so.

        Leaving it `pending` would make the recording page promise a
        compte-rendu that is never coming.
        """
        summary_job.status = AiJobStatusChoices.FAILED
        summary_job.save(update_fields=["status"])
        return Response({"error": message}, status=http_status)

    # Same request the audio path makes, field for field.
    try:
        created = requests_lib.post(
            _summary_service_url("async-jobs/summarize/"),
            json={
                "user_sub": file.creator.sub,
                "user_email": file.creator.email,
                "language": ai_job.language,
                "content": format_transcript(transcript),
            },
            headers={"Authorization": f"Bearer {settings.AI_SERVICE_API_KEY}"},
            timeout=30,
        )
        created.raise_for_status()
    except requests_lib.RequestException as exc:
        logger.error("Creating the summary job for file %s failed: %s", file.id, exc)
        return failed(f"Le compte-rendu n'a pas pu être lancé : {exc}")

    try:
        remote_job_id = created.json()["job_id"]
    except (ValueError, KeyError):
        return failed(
            "Le service de résumé n'a pas renvoyé d'identifiant de tâche pour "
            "le compte-rendu."
        )

    summary_job.remote_job_id = remote_job_id
    summary_job.save(update_fields=["remote_job_id"])

    summary_url, error = _summarize_remotely(remote_job_id=remote_job_id)
    if error is not None:
        return failed(error, http_status=status.HTTP_504_GATEWAY_TIMEOUT)

    try:
        download = requests_lib.get(summary_url, timeout=(10, 60))
        download.raise_for_status()
    except requests_lib.RequestException as exc:
        logger.error("Downloading the summary of file %s failed: %s", file.id, exc)
        return failed(f"Le compte-rendu produit n'a pas pu être récupéré : {exc}")

    storage = get_storage_for_file(file)
    try:
        storage.connection.meta.client.put_object(
            Bucket=get_storage_bucket_name(storage),
            Key=summary_job.key,
            Body=download.content,
            ContentType="text/plain",
        )
    except (BotoCoreError, ClientError, OSError) as exc:
        logger.error("Could not store the summary of %s: %s", file.id, exc)
        return failed(f"Le compte-rendu n'a pas pu être enregistré : {exc}")

    summary_job.status = AiJobStatusChoices.SUCCESS
    summary_job.save(update_fields=["status"])

    # Rendered by the model, not here: `to_markdown` is what the recording
    # page's own "ouvrir dans Docs" would have produced for a summary job.
    #
    # Filed under the import's parent when the caller sent one, so the three
    # documents of one import sit in the same tree. The id comes from the
    # browser rather than from here: this is a separate request, minutes after
    # the import, and nothing on the server remembers the parent. The only Docs
    # id this flow persists is `AiFileJob.docs_app_id`, the corrected document,
    # and the one Docs route the server-to-server key opens is
    # `create-for-owner` -- there is no route that answers "what is the parent
    # of this document". Storing it would have meant a migration; sending it
    # back does not. A caller that has no parent id gets a root document, as
    # before.
    document = _push_document(
        request.user,
        kind=DOC_SUMMARY,
        label="Compte-rendu",
        log_subject=file.id,
        title=f"{file.title} — compte-rendu"[:255],
        markdown=summary_job.to_markdown(file.creator.language),
        parent_id=parent_id,
    )
    if document["docs_app_id"]:
        summary_job.docs_app_id = document["docs_app_id"]
        summary_job.save(update_fields=["docs_app_id"])

    logger.info("Compte-rendu published for imported file %s", file.id)
    return Response({"document": document}, status=status.HTTP_201_CREATED)
