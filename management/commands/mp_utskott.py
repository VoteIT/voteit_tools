from django.core.management import BaseCommand
from django.db import models
from django.template.loader import render_to_string

from voteit.meeting.models import Meeting
from voteit.proposal.rest_api.serializers import GenericProposalSerializer
from voteit.proposal.workflows import ProposalWf
from voteit.reactions.models import ReactionButton


class Command(BaseCommand):
    help = "Utskottsprotokoll"
    PROPOSAL_WF_STATES = set(ProposalWf.states) - {ProposalWf.RETRACTED}

    def add_arguments(self, parser):
        parser.add_argument("-m", help="Meeting pk", required=True)
        parser.add_argument(
            "-t",
            help="Taggar, kan skrivas som lista med mellanslag",
            action="extend",
            nargs="+",
            type=str,
        )
        parser.add_argument(
            "-b",
            help="Knappar att inkludera - den första används som huvudförslag!",
            required=True,
            action="extend",
            nargs="+",
            type=int,
        )
        parser.add_argument(
            "--all-btns",
            help="Inkludera alla knappar",
            action="store_true",
        )
        parser.add_argument(
            "-g",
            help="Inkludera kommentarer från utskottets mötesgrupp, ange grupp_id för gruppen",
        )

    def handle(self, *args, **options):
        meeting: Meeting = Meeting.objects.get(pk=options.get("m"))
        # Buttons
        button_pks = options.get("b")
        utskottets_btn = ReactionButton.objects.get(pk=button_pks[0])
        assert utskottets_btn.flag_mode, "Utskottets knapp måste vara flagga"
        btn_qs = meeting.reaction_buttons.all()
        if missing := set(button_pks) - set(btn_qs.values_list("pk", flat=True)):
            exit(
                "The following button pks aren't valid for this meeting: %s"
                % ", ".join(str(x) for x in missing)
            )
        if not options.get("all_btns"):
            btn_qs = btn_qs.filter(pk__in=button_pks)
        btn_map = {}
        for btn_vals in btn_qs.values("pk", "title", "flag_mode", "target", "color"):
            btn_map[btn_vals["pk"]] = dict(btn_vals)
        # Groups
        utskottets_grupp = None
        if groupid := options.get("g"):
            utskottets_grupp = meeting.groups.get(groupid=groupid)
        # AIs
        ai_qs = meeting.agenda_items.all()
        if tags := options.get("t", []):
            ai_qs = ai_qs.filter(tags__overlap=tags)
        if not ai_qs.exists():
            exit("Inga dagordningspunkter matchade")

        rendered_sections = []
        for ai in ai_qs:
            all_reactions = (
                ai.reactions.filter(button__in=btn_qs)
                .values("object_id", "button")
                .annotate(count=models.Count("pk"))
                .order_by()
            )
            reactions_map = {}
            for reaction in all_reactions:
                objects = reactions_map.setdefault(reaction["object_id"], [])
                reaction["button"] = btn_map[reaction["button"]]
                objects.append(reaction)

            # Export ai
            prop_qs = ai.proposals.filter(
                state__in=self.PROPOSAL_WF_STATES
            ).select_subclasses()
            selected_proposals_rendered = []
            other_proposals_rendered = []

            meeting_groups_map = {x.pk: x for x in meeting.groups.all()}
            users_map = {
                x.pk: x
                for x in meeting.participants.filter(
                    pk__in=prop_qs.values_list("author", flat=True)
                )
            }
            paragraph_tag_map = {x.pk: x.tag for x in ai.text_paragraphs.all()}
            for prop in prop_qs:
                serializer = GenericProposalSerializer(prop)
                data = {**serializer.data}
                try:
                    data["reactions"] = reactions_map[data["pk"]]
                except KeyError:
                    data["reactions"] = []
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
                # And attach group comments regarding this
                if utskottets_grupp:
                    data["discussions"] = list(
                        ai.discussions.filter(
                            meeting_group=utskottets_grupp,
                            tags__contains=[prop.prop_id],
                        ).order_by("created")
                    )

                data["utskottets"] = False
                for i, button in enumerate(data["reactions"]):
                    if button["button"]["pk"] == utskottets_btn.pk:
                        data["utskottets"] = bool(button["count"])
                        data["popitem"] = i
                        break
                if data["utskottets"]:
                    # Remove reaction button corresponding to group
                    data["reactions"].pop(data.pop("popitem"))
                    selected_proposals_rendered.append(
                        render_to_string(
                            "mp_utskott/proposal.html",
                            {"proposal": data},
                        )
                    )
                else:
                    other_proposals_rendered.append(
                        render_to_string("mp_utskott/proposal.html", {"proposal": data})
                    )

            rendered_sections.append(
                render_to_string(
                    "mp_utskott/ai.html",
                    {
                        "agenda_item": ai,
                        "selected_proposals": selected_proposals_rendered,
                        "other_proposals": other_proposals_rendered,
                    },
                )
            )
        output = render_to_string(
            "mp_utskott/utskott.html",
            {
                "title": f"Utskottsprotokoll från {meeting.title}",
                "rendered_ais": rendered_sections,
            },
        )
        self.stdout.write(output)
