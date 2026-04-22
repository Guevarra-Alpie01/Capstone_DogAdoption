from types import SimpleNamespace

from django.urls import reverse


STAFF_PERMISSION_FIELDS = (
    "can_create_posts",
    "can_view_post_history",
    "can_view_status_cards",
    "can_manage_capture_requests",
    "can_access_registration",
    "can_access_registration_list",
    "can_access_vaccination",
    "can_access_vaccination_list",
    "can_access_citations",
)

STAFF_PERMISSION_GROUPS = (
    {
        "title": "Posts & Dashboard Access",
        "description": "Choose what this staff account can do on the Home dashboard.",
        "items": (
            {
                "name": "can_create_posts",
                "label": "Can create posts",
                "help": "Allow publishing rescued dog posts from the Home page.",
            },
            {
                "name": "can_view_post_history",
                "label": "Can view history/archive",
                "help": "Allow opening the archived post history page.",
            },
            {
                "name": "can_view_status_cards",
                "label": "Can view status cards",
                "help": "Allow viewing the Home dashboard status cards and related request actions.",
            },
        ),
        "note": "Appointment dates remain admin-only.",
    },
    {
        "title": "Requests Page Access",
        "description": "This gives full access to the Requests page and its tools.",
        "items": (
            {
                "name": "can_manage_capture_requests",
                "label": "Full Requests page access",
                "help": "Allow the same dog capture request workflow shown to the admin.",
            },
        ),
    },
    {
        "title": "Registration Management",
        "description": "Grant access to specific registration and health record sections.",
        "items": (
            {
                "name": "can_access_registration",
                "label": "Registration",
                "help": "Allow opening the dog registration form.",
            },
            {
                "name": "can_access_registration_list",
                "label": "Registration List",
                "help": "Allow viewing saved registration records.",
            },
            {
                "name": "can_access_vaccination",
                "label": "Vaccination",
                "help": "Allow managing vaccination entries and medical records.",
            },
            {
                "name": "can_access_vaccination_list",
                "label": "Vaccination List",
                "help": "Allow viewing certificates and exports.",
            },
            {
                "name": "can_access_citations",
                "label": "Citation Management",
                "help": "Allow creating citations and opening the penalty manager.",
            },
        ),
    },
)

ADMIN_ROUTE_RULES = {
    "post_list": {"any_of": ("can_access_posts_dashboard",)},
    "create_post": {"any_of": ("can_create_posts",)},
    "update_post": {"any_of": ("can_create_posts",)},
    "toggle_post_phase": {"any_of": ("can_create_posts",)},
    "finalize_post": {"any_of": ("can_create_posts",)},
    "delete_post": {"any_of": ("can_create_posts",)},
    "post_history": {"any_of": ("can_view_post_history",)},
    "user_adoption_history": {"any_of": ("can_view_post_history",)},
    "claim_requests": {"any_of": ("can_view_status_cards",)},
    "adoption_requests": {"any_of": ("can_view_status_cards",)},
    "update_request": {"any_of": ("can_view_status_cards",)},
    "user_post_requests": {"any_of": ("can_create_posts",)},
    "user_post_request_action": {"any_of": ("can_create_posts",)},
    "requests": {"any_of": ("can_manage_capture_requests",)},
    "update_dog_capture_request": {"any_of": ("can_manage_capture_requests",)},
    "register_dogs": {"any_of": ("can_access_registration",)},
    "registration_record": {"any_of": ("can_access_registration_list",)},
    "registration_owner_profile": {"admin_only": True},
    "download_registration": {"any_of": ("can_access_registration_list",)},
    "dog_certificate": {"any_of": ("can_access_vaccination",)},
    "med_records": {"any_of": ("can_access_vaccination",)},
    "certificate_list": {"any_of": ("can_access_vaccination_list",)},
    "certificate_print": {"any_of": ("can_access_vaccination", "can_access_vaccination_list")},
    "export_certificates_pdf": {"any_of": ("can_access_vaccination_list",)},
    "export_certificates_word": {"any_of": ("can_access_vaccination_list",)},
    "export_certificates_excel": {"any_of": ("can_access_vaccination_list",)},
    "bulk_certificate_print": {"any_of": ("can_access_vaccination_list",)},
    "citation_create": {"any_of": ("can_access_citations",)},
    "citation_print_lookup": {"any_of": ("can_access_citations",)},
    "citation_print": {"any_of": ("can_access_citations",)},
    "penalty_manage": {"any_of": ("can_access_citations",)},
    "admin_users": {"admin_only": True},
    "admin_user_detail": {"admin_only": True},
    "admin_user_search": {"admin_only": True},
    "admin_user_violations": {"admin_only": True},
    "admin_user_violation_letter": {"admin_only": True},
    "admin_announcements": {"admin_only": True},
    "announcement_create": {"admin_only": True},
    "announcement_create_form": {"admin_only": True},
    "announcement_edit": {"admin_only": True},
    "announcement_update_bucket": {"admin_only": True},
    "announcement_delete": {"admin_only": True},
    "analytics_dashboard": {"admin_only": True},
}


def _blank_access():
    access = {name: False for name in STAFF_PERMISSION_FIELDS}
    access.update(
        {
            "is_staff_account": False,
            "is_managed_staff": False,
            "is_full_admin": False,
            "can_access_posts_dashboard": False,
            "can_access_users": False,
            "can_manage_staff_accounts": False,
            "can_access_announcements": False,
            "can_access_analytics": False,
            "can_access_register_area": False,
            "landing_url": reverse("user:login"),
            "home_url": "",
            "display_role": "Visitor",
        }
    )
    return access


def _route_candidates(access):
    return (
        ("can_access_posts_dashboard", reverse("dogadoption_admin:post_list")),
        ("can_manage_capture_requests", reverse("dogadoption_admin:requests")),
        ("can_access_registration", reverse("dogadoption_admin:register_dogs")),
        ("can_access_registration_list", reverse("dogadoption_admin:registration_record")),
        ("can_access_vaccination", reverse("dogadoption_admin:dog_certificate")),
        ("can_access_vaccination_list", reverse("dogadoption_admin:certificate_list")),
        ("can_access_citations", reverse("dogadoption_admin:citation_create")),
        ("can_access_announcements", reverse("dogadoption_admin:admin_announcements")),
        ("can_access_analytics", reverse("dogadoption_admin:analytics_dashboard")),
    )


def get_staff_access_record(user):
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
        return None
    try:
        return user.staff_access
    except Exception:
        return None


def build_admin_access(user):
    access = _blank_access()
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
        return access

    access["is_staff_account"] = True
    access["home_url"] = reverse("dogadoption_admin:post_list")
    staff_access = get_staff_access_record(user)
    access["is_managed_staff"] = staff_access is not None
    access["is_full_admin"] = staff_access is None

    if staff_access is None:
        for name in STAFF_PERMISSION_FIELDS:
            access[name] = True
        access["can_access_users"] = True
        access["can_manage_staff_accounts"] = True
        access["can_access_announcements"] = True
        access["can_access_analytics"] = True
        access["display_role"] = "Administrator"
    else:
        for name in STAFF_PERMISSION_FIELDS:
            access[name] = bool(getattr(staff_access, name, False))
        access["display_role"] = "Staff Account"

    access["can_access_posts_dashboard"] = any(
        access[name]
        for name in ("can_create_posts", "can_view_post_history", "can_view_status_cards")
    )
    access["can_access_register_area"] = any(
        access[name]
        for name in (
            "can_access_registration",
            "can_access_registration_list",
            "can_access_vaccination",
            "can_access_vaccination_list",
            "can_access_citations",
            "can_access_users",
        )
    )

    landing_url = reverse("dogadoption_admin:admin_edit_profile")
    for permission_name, url in _route_candidates(access):
        if access.get(permission_name):
            landing_url = url
            break
    access["landing_url"] = landing_url
    return access


def get_admin_access(user):
    if user is None:
        return _blank_access()
    if not getattr(user, "is_authenticated", False) or not getattr(user, "is_staff", False):
        return build_admin_access(user)

    cached = getattr(user, "_dogadoption_admin_access_cache", None)
    if cached is None:
        cached = build_admin_access(user)
        try:
            setattr(user, "_dogadoption_admin_access_cache", cached)
        except (AttributeError, TypeError):
            return cached
    return cached


def get_admin_access_namespace(user):
    return SimpleNamespace(**get_admin_access(user))


def get_staff_landing_url(user):
    return get_admin_access(user).get("landing_url") or reverse("dogadoption_admin:admin_edit_profile")


def is_route_allowed(access, route_name):
    if access.get("is_full_admin"):
        return True
    rule = ADMIN_ROUTE_RULES.get(route_name) or {}
    if rule.get("admin_only"):
        return False
    any_of = rule.get("any_of") or ()
    if any_of:
        return any(access.get(name) for name in any_of)
    return True


def get_staff_permission_summary(record):
    summary = []
    if getattr(record, "can_create_posts", False):
        summary.append("Create posts")
    if getattr(record, "can_view_post_history", False):
        summary.append("Post history")
    if getattr(record, "can_view_status_cards", False):
        summary.append("Status cards")
    if getattr(record, "can_manage_capture_requests", False):
        summary.append("Requests page")
    if getattr(record, "can_access_registration", False):
        summary.append("Registration")
    if getattr(record, "can_access_registration_list", False):
        summary.append("Registration list")
    if getattr(record, "can_access_vaccination", False):
        summary.append("Vaccination")
    if getattr(record, "can_access_vaccination_list", False):
        summary.append("Vaccination list")
    if getattr(record, "can_access_citations", False):
        summary.append("Citations")
    return summary
