from django.core.cache import cache


ANALYTICS_DASHBOARD_CACHE_KEY = "analytics_dashboard_context_v1"


def invalidate_analytics_dashboard_cache():
    cache.delete(ANALYTICS_DASHBOARD_CACHE_KEY)
