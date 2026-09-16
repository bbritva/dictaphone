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
                # Demo-only, for the /demo page. Proxies the summary service's
                # own demo route; touches no File and no AiFileJob.
                path(
                    "demo/transcript-quality/run/",
                    demo.run_transcript_quality_demo,
                    name="demo-transcript-quality-run",
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
