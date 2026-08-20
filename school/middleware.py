import ipaddress
import uuid

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone

from .models import PageVisit


class PageVisitMiddleware:
    """Aggregate successful HTML page views by IP and semantic route."""

    EXCLUDED_PREFIXES = ("/api/", "/static/", "/media/", "/.well-known/")
    VISITOR_COOKIE = "muellima_visitor_id"
    VISITOR_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
    PAGE_CATEGORIES = {
        "home": "homepage",
        "course_page": "course",
        "lesson_page": "lessons",
        "profile": "profile",
        "plans": "plans",
        "login": "login",
        "register": "register",
        "staff_dashboard": "dashboard",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        visitor_id, is_new_visitor = self._visitor_id(request)
        response = self.get_response(request)
        if self._should_track(request, response):
            self._record(request, visitor_id)
        if is_new_visitor:
            response.set_cookie(
                self.VISITOR_COOKIE,
                str(visitor_id),
                max_age=self.VISITOR_COOKIE_MAX_AGE,
                httponly=True,
                secure=request.is_secure(),
                samesite="Lax",
            )
        return response

    def _visitor_id(self, request):
        raw_value = request.COOKIES.get(self.VISITOR_COOKIE, "")
        try:
            return uuid.UUID(raw_value), False
        except (ValueError, AttributeError, TypeError):
            return uuid.uuid4(), True

    def _should_track(self, request, response):
        content_type = response.get("Content-Type", "").lower()
        return (
            request.method == "GET"
            and response.status_code == 200
            and content_type.startswith("text/html")
            and not request.path.startswith(self.EXCLUDED_PREFIXES)
        )

    def _client_ip(self, request):
        candidates = []
        if settings.TRUST_PROXY_IP_HEADERS:
            candidates.append(request.META.get("HTTP_X_REAL_IP", ""))
            forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
            if forwarded:
                candidates.append(forwarded.split(",", 1)[0].strip())
        candidates.append(request.META.get("REMOTE_ADDR", ""))

        for candidate in candidates:
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
        return None

    def _record(self, request, visitor_id):
        ip_address = self._client_ip(request)
        if not ip_address:
            return

        user_id = request.user.pk if request.user.is_authenticated else None
        if user_id is not None:
            visitor_id = self._merge_authenticated_visitor(request.user, visitor_id)

        url_name = getattr(request.resolver_match, "url_name", "") or "other"
        category = self.PAGE_CATEGORIES.get(url_name, url_name[:100])
        lookup = {"visitor_id": visitor_id, "category": category}
        updates = {
            "visit_count": F("visit_count") + 1,
            "ip_address": ip_address,
            "last_visited_at": timezone.now(),
        }
        if user_id is not None:
            updates["last_user_id"] = user_id
        if PageVisit.objects.filter(**lookup).update(**updates):
            return
        try:
            PageVisit.objects.create(
                **lookup,
                ip_address=ip_address,
                last_user_id=user_id,
            )
        except IntegrityError:
            # A concurrent first visit may have created the same aggregate.
            PageVisit.objects.filter(**lookup).update(**updates)

    @transaction.atomic
    def _merge_authenticated_visitor(self, user, incoming_visitor_id):
        """Consolidate browser prospects under the normalized account email."""
        normalized_email = (user.email or "").strip().casefold()
        if not normalized_email:
            PageVisit.objects.filter(
                visitor_id=incoming_visitor_id,
                last_user_id__isnull=True,
            ).update(last_user_id=user.pk)
            return incoming_visitor_id

        canonical_id = uuid.uuid5(uuid.NAMESPACE_URL, f"muellima:user:{normalized_email}")
        source_visits = list(
            PageVisit.objects.select_for_update()
            .filter(
                Q(visitor_id=incoming_visitor_id)
                | Q(last_user__email__iexact=normalized_email)
            )
            .exclude(visitor_id=canonical_id)
            .order_by("first_visited_at", "id")
        )

        for source in source_visits:
            target = (
                PageVisit.objects.select_for_update()
                .filter(visitor_id=canonical_id, category=source.category)
                .first()
            )
            if target:
                newest = source if source.last_visited_at > target.last_visited_at else target
                PageVisit.objects.filter(pk=target.pk).update(
                    visit_count=target.visit_count + source.visit_count,
                    ip_address=newest.ip_address,
                    last_user_id=user.pk,
                    first_visited_at=min(target.first_visited_at, source.first_visited_at),
                    last_visited_at=max(target.last_visited_at, source.last_visited_at),
                )
                source.delete()
            else:
                PageVisit.objects.filter(pk=source.pk).update(
                    visitor_id=canonical_id,
                    last_user_id=user.pk,
                )

        PageVisit.objects.filter(visitor_id=canonical_id).update(last_user_id=user.pk)
        return canonical_id
