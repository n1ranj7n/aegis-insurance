"""Template context processors."""

from django.conf import settings


def demo_banner(request):
    """Expose demo banner text and demo credentials to every template."""
    return {
        "DEMO_BANNER_TEXT": settings.DEMO_BANNER_TEXT,
        "DEMO_USERNAME": settings.DEMO_USERNAME,
        "DEMO_PASSWORD": settings.DEMO_PASSWORD,
    }
