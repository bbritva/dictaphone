"""Tests for the summarize half of the transcript import flow.

The route publishes the compte-rendu of an imported recording to Docs. It runs
minutes after the import, in its own request, so it cannot know on its own which
Docs document the import's two transcript documents were filed under: the
browser hands that id back in the body. These tests pin the three ways that can
go -- sent, omitted, malformed.
"""

from unittest.mock import Mock, patch

import pytest
from rest_framework import status
from rest_framework.test import APIClient

from core import factories
from core.models import (
    AiFileJob,
    AiJobStatusChoices,
    AiJobTypeChoices,
    FileSourceChoices,
)

pytestmark = pytest.mark.django_db

SUMMARIZE_URL = "/api/v1.0/demo/transcript-quality/ai-jobs/{pk}/summarize/"

#: The smallest body `WhisperXResponse` accepts, so the route gets past parsing
#: the stored transcript without object storage being involved.
STORED_TRANSCRIPT = (
    b'{"segments": ['
    b'{"start": 0.0, "end": 1.0, "text": "Bonjour.", "words": [], '
    b'"speaker": "SPEAKER_00"}'
    b'], "word_segments": []}'
)


@pytest.fixture(name="imported")
def imported_fixture():
    """A finished transcript job on a recording the import created."""
    user = factories.UserFactory()
    ai_job = factories.AiFileJobFactory(
        file__creator=user,
        file__source=FileSourceChoices.IMPORTED_TRANSCRIPT,
        type=AiJobTypeChoices.TRANSCRIPT,
        status=AiJobStatusChoices.SUCCESS,
    )
    return user, ai_job


@pytest.fixture(name="pipeline")
def pipeline_fixture():
    """Stub every remote leg of the route and hand back the Docs push mock.

    Everything between "read the stored transcript" and "publish the result" is
    a network call or object storage; none of it is what these tests are about.
    What is left real is the path the `parent_id` travels: request body ->
    `_parent_id_of` -> `_push_document` -> `push_markdown_to_docs`.
    """
    with (
        patch("core.api.demo._stored_transcript_of", return_value=STORED_TRANSCRIPT),
        patch("core.api.demo.requests_lib.post") as mock_post,
        patch(
            "core.api.demo._summarize_remotely",
            return_value=("https://summary.example.com/result.txt", None),
        ),
        patch("core.api.demo.requests_lib.get") as mock_get,
        patch("core.api.demo.get_storage_for_file"),
        patch("core.api.demo.get_storage_bucket_name", return_value="bucket"),
        patch("core.models.AiFileJob.to_markdown", return_value="# Résumé"),
        patch(
            "core.api.demo.push_markdown_to_docs", return_value="summary-doc-id"
        ) as mock_push,
    ):
        mock_post.return_value = Mock(
            raise_for_status=Mock(return_value=None),
            json=Mock(return_value={"job_id": "summarize-remote-id"}),
        )
        mock_get.return_value = Mock(
            raise_for_status=Mock(return_value=None), content=b"Le compte-rendu."
        )
        yield mock_push


def test_api_demo_summarize_imported_publishes_under_the_given_parent(
    imported, pipeline
):
    """A `parent_id` in the body must reach the Docs push as a parent."""
    user, ai_job = imported
    parent_id = "1b0f8b3e-2b8a-4c1f-9d2e-6a7b8c9d0e1f"

    client = APIClient()
    client.force_login(user)

    response = client.post(
        SUMMARIZE_URL.format(pk=ai_job.id),
        {"parent_document_id": parent_id},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["document"]["docs_app_id"] == "summary-doc-id"

    assert pipeline.call_args.kwargs["parent_id"] == parent_id

    summary_job = AiFileJob.objects.get(
        file=ai_job.file, type=AiJobTypeChoices.SUMMARIZE
    )
    assert summary_job.status == AiJobStatusChoices.SUCCESS
    assert summary_job.docs_app_id == "summary-doc-id"


def test_api_demo_summarize_imported_publishes_at_root_without_parent(
    imported, pipeline
):
    """Omitting the field is the old call and must still publish a root."""
    user, ai_job = imported

    client = APIClient()
    client.force_login(user)

    response = client.post(SUMMARIZE_URL.format(pk=ai_job.id), {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert pipeline.call_args.kwargs["parent_id"] is None


def test_api_demo_summarize_imported_accepts_an_explicit_null_parent(
    imported, pipeline
):
    """A client whose import had no parent may send null rather than omit it."""
    user, ai_job = imported

    client = APIClient()
    client.force_login(user)

    response = client.post(
        SUMMARIZE_URL.format(pk=ai_job.id), {"parent_document_id": None}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert pipeline.call_args.kwargs["parent_id"] is None


def test_api_demo_summarize_imported_rejects_a_malformed_parent(imported, pipeline):
    """A value that is not a UUID is a 400, and costs no model call."""
    user, ai_job = imported

    client = APIClient()
    client.force_login(user)

    response = client.post(
        SUMMARIZE_URL.format(pk=ai_job.id),
        {"parent_document_id": "not-a-uuid"},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {
        "error": "« parent_document_id » n'est pas un identifiant de document valide."
    }

    pipeline.assert_not_called()
    # Refused before anything was created: no half-finished summary job is left
    # behind for the recording page to promise.
    assert not AiFileJob.objects.filter(
        file=ai_job.file, type=AiJobTypeChoices.SUMMARIZE
    ).exists()
