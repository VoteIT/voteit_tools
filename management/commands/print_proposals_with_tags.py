from itertools import groupby

from django.core.management import BaseCommand
from django.template.loader import render_to_string

from voteit.meeting.models import Meeting
from voteit.proposal.models import Proposal
from voteit.proposal.models import TextParagraph
from voteit.proposal.rest_api.serializers import GenericProposalSerializer


class Command(BaseCommand):
    help = "Print proposals with a certain tag"

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True)
        parser.add_argument(
            "-t",
            help="Förslagstagg(ar)",
            type=str,
            required=True,
            action="extend",
            nargs="+",
        )

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        tags = options.get("t")
        prop_qs = (
            Proposal.objects.filter(tags__contains=tags, agenda_item__meeting=meeting)
            .select_subclasses()
            .order_by("agenda_item__order")
            .select_related("agenda_item")
        )
        # Other things needed
        meeting_groups_map = {x.pk: x for x in meeting.groups.all()}
        users_map = {
            x.pk: x
            for x in meeting.participants.filter(
                pk__in=prop_qs.values_list("author", flat=True)
            )
        }
        paragraph_tag_map = {
            x.pk: x.tag
            for x in TextParagraph.objects.filter(agenda_item__meeting=meeting)
        }
        rendered_ais = []
        for agenda_item, proposals in groupby(
            prop_qs, lambda proposal: proposal.agenda_item
        ):
            rendered_proposals = []
            for prop in proposals:
                serializer = GenericProposalSerializer(prop)
                data = {**serializer.data}
                # Meeting Group
                try:
                    data["meeting_group"] = meeting_groups_map[data["meeting_group"]]
                except KeyError:
                    data["meeting_group"] = None
                # Author
                try:
                    data["author"] = users_map[data["author"]]
                except KeyError:
                    data["author"] = {
                        "userid": "",
                        "get_full_name": "(Removed user)",
                    }
                try:
                    data["ptag"] = paragraph_tag_map[data["paragraph"]]
                except KeyError:
                    pass
                # Adjust tags and remove prop id
                if prop.prop_id in data["tags"]:
                    data["tags"].remove(prop.prop_id)
                rendered_proposals.append(
                    render_to_string("voteit/proposal.html", {"proposal": data})
                )
            rendered_ais.append(
                render_to_string(
                    "voteit/ai.html",
                    {"agenda_item": agenda_item, "proposals": rendered_proposals},
                )
            )
        self.stdout.write(
            render_to_string(
                "voteit/meeting.html",
                {"rendered_ais": rendered_ais, "title": meeting.title},
            )
        )
