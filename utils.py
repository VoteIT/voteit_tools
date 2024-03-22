from contextlib import contextmanager
from datetime import date
from functools import reduce
from time import perf_counter

from django.db import models
from django.template.loader import render_to_string

from envelope.models import Connection
from voteit.agenda.models import AgendaItem
from voteit.discussion.models import DiscussionPost
from voteit.invites.models import MeetingInvite
from voteit.organisation.models import Organisation
from voteit.proposal.models import Proposal


@contextmanager
def exectime() -> float:
    start = perf_counter()
    yield lambda: perf_counter() - start


def render_org_stats(
    organisation: Organisation, year: int, lmeeting: int = 500, smeeting: int = 15
) -> str:

    context = {
        "organisation": organisation,
        "year": year,
        "smeeting": smeeting,
        "lmeeting": lmeeting,
    }

    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    meeting_qs = (
        organisation.meetings.filter(created__gte=year_start, created__lte=year_end)
        .annotate(participants_count=models.Count(models.F("participants")))
        .order_by("participants_count")
    )
    # Möten
    context["large_meeting_count"] = meeting_qs.filter(
        participants_count__gte=lmeeting
    ).count()
    context["meeting_count"] = meeting_qs.filter(
        participants_count__gte=smeeting
    ).count()
    context["m_too_small_count"] = meeting_qs.filter(
        participants_count__lt=smeeting
    ).count()
    # Annat kul
    all_meetings_qs = organisation.meetings.all()
    context["inv_count"] = MeetingInvite.objects.filter(
        created__gte=year_start,
        created__lte=year_end,
        meeting__in=all_meetings_qs,
    ).count()
    ai_qs = AgendaItem.objects.filter(meeting__in=all_meetings_qs)
    context["prop_count"] = Proposal.objects.filter(
        created__gte=year_start, created__lte=year_end, agenda_item__in=ai_qs
    ).count()
    context["disc_count"] = DiscussionPost.objects.filter(
        created__gte=year_start, created__lte=year_end, agenda_item__in=ai_qs
    ).count()

    # Antal användare under året
    context["active_users"] = active_users = (
        organisation.users.filter(
            connections__online_at__gte=year_start,
            connections__online_at__lte=year_end,
        )
        .distinct()
        .count()
    )

    # Uppkopplingar och Effektiv användningstid
    ts_sum = []
    for online_ts, offline_ts in (
        Connection.objects.filter(user__in=organisation.users.all())
        .filter(online_at__gte=year_start, online_at__lte=year_end)
        .exclude(offline_at__isnull=True)
        .values_list("online_at", "offline_at")
    ):
        ts_sum.append(offline_ts - online_ts)
    if ts_sum:
        ts_total = reduce(lambda x, y: x + y, ts_sum)
        # Jo ett bättre sätt för decimaler vore bra :)

        context["users_days"] = users_days = ts_total.days + round(
            ts_total.seconds / (24 * 60 * 60) * 100
        )
        context["mean_hours"] = round((users_days / active_users) * 24, ndigits=2)
    else:
        context["users_days"] = 0
        context["mean_hours"] = 0
    context["connections"] = len(ts_sum)
    return render_to_string("voteit/org_stat.html", context)
