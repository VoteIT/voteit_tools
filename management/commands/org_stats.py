from __future__ import annotations

import csv
import json
from datetime import datetime
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management import BaseCommand
from django.db import models
from pydantic import BaseModel
from rest_framework import serializers

from envelope.models import Connection
from voteit.discussion.models import DiscussionPost
from voteit.meeting.models import Meeting
from voteit.organisation.models import Organisation
from voteit.poll.models import Poll
from voteit.poll.models import Vote
from voteit.proposal.models import Proposal

User = get_user_model()


class MeetingSerializer(serializers.ModelSerializer):
    participants = serializers.IntegerField(source="participants_count")
    polls = serializers.SerializerMethodField()
    agenda_items = serializers.SerializerMethodField()
    votes = serializers.SerializerMethodField()
    proposals = serializers.SerializerMethodField()
    discussion_posts = serializers.SerializerMethodField()

    class Meta:
        model = Meeting
        fields = [
            # "title",
            "participants",
            "agenda_items",
            "proposals",
            "discussion_posts",
            "polls",
            "votes",
        ]

    def get_polls(self, instance: Meeting):
        return instance.polls.count()

    def get_agenda_items(self, instance: Meeting):
        return instance.agenda_items.count()

    def get_votes(self, instance: Meeting):
        return Vote.objects.filter(poll__meeting=instance).count()

    def get_discussion_posts(self, instance: Meeting):
        return DiscussionPost.objects.filter(agenda_item__meeting=instance).count()

    def get_proposals(self, instance: Meeting):
        return Proposal.objects.filter(agenda_item__meeting=instance).count()


class ExportOrgSerializer(serializers.ModelSerializer):
    active_users = serializers.SerializerMethodField()
    new_users = serializers.SerializerMethodField()
    online_days = serializers.SerializerMethodField()
    online_hours = serializers.SerializerMethodField()
    meeting_details = serializers.SerializerMethodField()
    proposals = serializers.SerializerMethodField()
    votes = serializers.SerializerMethodField()
    polls = serializers.SerializerMethodField()
    discussion_posts = serializers.SerializerMethodField()
    meetings = serializers.SerializerMethodField()

    class Meta:
        model = Organisation
        fields = [
            "title",
            "active_users",
            "new_users",
            "online_days",
            "online_hours",
            "meeting_details",
            "meetings",
            "proposals",
            "votes",
            "polls",
            "discussion_posts",
        ]

    def get_active_users(self, instance: Organisation):
        return User.objects.filter(
            pk__in=self.con_qs(instance).values_list("user", flat=True)
        ).count()

    def get_online_days(self, instance: Organisation):
        qs = self.con_qs(instance).annotate(
            duration=models.F("offline_at") - models.F("online_at")
        )
        delta: timedelta = qs.aggregate(models.Sum("duration"))["duration__sum"]
        if delta is None:
            return 0
        return delta.days

    def get_online_hours(self, instance: Organisation):
        qs = self.con_qs(instance).annotate(
            duration=models.F("offline_at") - models.F("online_at")
        )
        delta: timedelta = qs.aggregate(models.Sum("duration"))["duration__sum"]
        if delta is None:
            return 0
        return round(delta.seconds / 60 / 60)

    def con_qs(self, instance: Organisation):
        return Connection.objects.filter(
            user__organisation=instance,
            last_action__gt=self.start_ts,
            last_action__lt=self.end_ts,
        )

    def meeting_qs(self, instance: Organisation):
        return instance.meetings.filter(
            start_time__gt=self.start_ts,
            start_time__lt=self.end_ts,
        )

    def get_new_users(self, instance: Organisation):
        return instance.users.filter(
            date_joined__gt=self.start_ts, date_joined__lt=self.end_ts
        ).count()

    def get_proposals(self, instance: Organisation):
        return Proposal.objects.filter(
            agenda_item__meeting__in=self.meeting_qs(instance)
        ).count()

    def get_votes(self, instance: Organisation):
        return Vote.objects.filter(poll__meeting__in=self.meeting_qs(instance)).count()

    def get_polls(self, instance: Organisation):
        return Poll.objects.filter(meeting__in=self.meeting_qs(instance)).count()

    def get_discussion_posts(self, instance: Organisation):
        return DiscussionPost.objects.filter(
            agenda_item__meeting__in=self.meeting_qs(instance)
        ).count()

    def get_meetings(self, instance: Organisation):
        return self.meeting_qs(instance).count()

    def get_meeting_details(self, instance: Organisation):
        if self.context["detailed_meetings"]:
            qs = (
                self.meeting_qs(instance)
                .annotate(
                    participants_count=models.Count("participants", distinct=True)
                )
                .filter(participants_count__gt=self.min_participants)
            )
            serializer = MeetingSerializer(qs, many=True)
            return serializer.data

    @property
    def start_ts(self):
        return self.context["sr"].start

    @property
    def end_ts(self):
        return self.context["sr"].end

    @property
    def min_participants(self):
        return self.context["min_participants"]


class SearchRange(BaseModel):
    start: datetime
    end: datetime


class Command(BaseCommand):
    help = "Generate organisation stats."

    def add_arguments(self, parser):
        parser.add_argument(
            "year",
            help="År som YYYY",
        )
        parser.add_argument(
            "-o",
            help="Organisations-pk, flera eller inget för alla",
            action="extend",
            nargs="+",
            type=int,
        )
        parser.add_argument(
            "-m",
            help="Ta med specifik mötesinfo",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "-p",
            help="Ta bort möten med mindre än detta antal deltagare - standard 20",
            default=20,
            type=int,
        )
        parser.add_argument("-f", help="Filnamn", required=True)
        parser.add_argument(
            "--csv",
            help="Total som CSV",
            action="store_true",
            default=False,
        )

    def handle(self, *args, **options):
        org_qs = Organisation.objects.all()
        if org_pks := options.get("o"):
            org_qs = org_qs.filter(pk__in=org_pks)
        year = options.get("year")
        sr = SearchRange(
            start=f"{year}-01-01T00:00:01+01", end=f"{year}-12-31T23:59:59+01"
        )
        self.stdout.write("Exporterar %s organisationer" % org_qs.count())
        serializer = ExportOrgSerializer(
            org_qs,
            many=True,
            context={
                "sr": sr,
                "min_participants": options.get("p"),
                "detailed_meetings": options.get("m"),
            },
        )
        if not serializer.data:
            exit("Ingen data matchar")
        if not options.get("m"):  # Cleanup
            for item in serializer.data:
                item.pop("meeting_details")
        filename = options.get("f")
        with open(filename, "w") as f:
            if options.get("csv"):
                # Printing csv
                writer = csv.DictWriter(f, fieldnames=list(serializer.child.fields))
                writer.writeheader()
                for row in serializer.data:
                    writer.writerow(row)
                self.stdout.write(
                    self.style.SUCCESS(
                        "CSV med %s rader skriven" % len(serializer.data)
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        "JSON med %s objekt skriven" % len(serializer.data)
                    )
                )
                json.dump(serializer.data, f)
