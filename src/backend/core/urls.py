"""URL configuration for the core app."""

from django.conf import settings
from django.urls import include, path

from lasuite.oidc_login.urls import urlpatterns as oidc_urls
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from core.api import (
    demo,
    get_app_configuration,
    get_mobile_app_download_page,
    viewsets,
)
from core.authentication.views import PKCEOAuthTokenExchangeView

# - Main endpoints
router = DefaultRouter()
router.register("users", viewsets.UserViewSet, basename="users")
router.register("files", viewsets.FileViewSet, basename="files")
router.register("ai-jobs", viewsets.AiJobViewSet, basename="ai-jobs")

urlpatterns = [
    path(
        f"api/{settings.API_VERSION}/",
        include(
            [
                *router.urls,
                *oidc_urls,
                path(
                    "oauth/token/",
                    PKCEOAuthTokenExchangeView.as_view(),
                    name="token_obtain_pair",
                ),
                path(
                    "oauth/token/refresh/",
                    TokenRefreshView.as_view(),
                    name="token_refresh",
                ),
                path("config/", get_app_configuration, name="config"),
                path(
                    "download-mobile-app/",
                    get_mobile_app_download_page,
                    name="download-mobile-app",
                ),
                # Demo-only. Proxies the summary service's own demo route.
                # This one and the job-backed one below write nothing: no File
                # and no AiFileJob is created, updated or deleted by either.
                path(
                    "demo/transcript-quality/run/",
                    demo.run_transcript_quality_demo,
                    name="demo-transcript-quality-run",
                ),
                # Same run, over a transcript already stored for an AI job,
                # for the panel on the recording page. Read-only.
                path(
                    "demo/transcript-quality/ai-jobs/<uuid:pk>/run/",
                    demo.run_transcript_quality_demo_on_job,
                    name="demo-transcript-quality-run-on-job",
                ),
                # Demo-only, and the one route here that keeps something:
                # corrects an uploaded transcript and stores the result as a
                # real recording. See `demo.import_transcript_as_recording`.
                path(
                    "demo/transcript-quality/import/",
                    demo.import_transcript_as_recording,
                    name="demo-transcript-quality-import",
                ),
                # Second half of the import flow: summarises the corrected
                # transcript of an imported recording and publishes it. Refuses
                # anything that did not come from an import, so the audio
                # pipeline's own summary stays the only one it ever has.
                path(
                    "demo/transcript-quality/ai-jobs/<uuid:pk>/summarize/",
                    demo.summarize_imported_recording,
                    name="demo-transcript-quality-summarize-imported",
                ),
                path(
                    "demo/transcript-quality/publish/",
                    demo.publish_transcript_quality_demo,
                    name="demo-transcript-quality-publish",
                ),
            ]
        ),
    ),
]
