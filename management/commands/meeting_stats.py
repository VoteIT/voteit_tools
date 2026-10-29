from django.core.management import BaseCommand
from django.db.models import Count

from voteit.discussion.models import DiscussionPost
from voteit.meeting.models import Meeting
from voteit.notes.models import Note
from voteit.poll.models import Vote
from voteit.proposal.models import Proposal
from voteit.speaker.models import Speaker


class Command(BaseCommand):
    help = "Print activity statistics for a meeting."

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True, type=int)

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options["m"])
        categories = [
            (
                "Proposals",
                Proposal.objects.filter(agenda_item__meeting=meeting),
                "author",
            ),
            (
                "Discussion posts",
                DiscussionPost.objects.filter(agenda_item__meeting=meeting),
                "author",
            ),
            ("Votes", Vote.objects.filter(poll__meeting=meeting), "user"),
            ("Notes", Note.objects.filter(meeting=meeting), "user"),
            (
                "Speaker entries",
                Speaker.objects.filter(
                    speaker_list__meeting=meeting, started__isnull=False
                ),
                "user",
            ),
        ]
        for button in meeting.reaction_buttons.filter(flag_mode=False):
            categories.append(
                (f"Reaction: {button.title[:20]}", button.reactions.all(), "user")
            )
        self.stdout.write(f"Meeting: {meeting.title} (pk {meeting.pk})")
        self.stdout.write(
            f"Participants: {meeting.participants.count()}   "
            f"Agenda items: {meeting.agenda_items.count()}   "
            f"Polls: {meeting.polls.count()}"
        )
        self.stdout.write("")
        self.stdout.write(f"{'Category':<30}{'Count':>8}{'Users':>8}")
        active_users = set()
        for label, qs, user_field in categories:
            # Count(distinct=True) skips NULL, i.e. proposals with deleted authors
            res = qs.aggregate(
                count=Count("pk"), users=Count(user_field, distinct=True)
            )
            self.stdout.write(f"{label:<30}{res['count']:>8}{res['users']:>8}")
            active_users.update(
                qs.exclude(**{f"{user_field}__isnull": True})
                .values_list(user_field, flat=True)
                .distinct()
            )
        self.stdout.write("")
        self.stdout.write(f"{'Any of the above':<30}{'':>8}{len(active_users):>8}")
        inactive = meeting.participants.exclude(pk__in=active_users).count()
        self.stdout.write(f"{'Observers/Inactive':<30}{'':>8}{inactive:>8}")
