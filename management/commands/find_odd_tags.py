from __future__ import annotations

import re
from collections import defaultdict
from random import shuffle

from bs4 import BeautifulSoup
from django.core.management import BaseCommand
from django.db import transaction

from voteit.agenda.models import AgendaItem
from voteit.core.testing import mk_hashtag
from voteit.proposal.models import Proposal
from voteit.discussion.models import DiscussionPost
from voteit.proposal.models import TextDocument

OK_TAG_PATTERN = re.compile(r"^[\w\\.\-]+$")
REPLACE_ANY_OTHER_PATTERN = re.compile(r"[^\w\\.]")
REMOVE_MANY_DASHES = re.compile(r"-{2,}")


def _reformat(tag):
    txt = re.sub(REPLACE_ANY_OTHER_PATTERN, "-", tag)
    txt = re.sub(REMOVE_MANY_DASHES, "-", txt)
    if txt.startswith("-"):
        txt = txt[1:]
    if txt.endswith("-"):
        txt = txt[:-1]
    return txt


def _explain(tag):
    print("'" + tag + "' -> " + _reformat(tag))


class Command(BaseCommand):
    # help = ""

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit", help="Commit result to db", action="store_true", default=False
        )

    def handle(self, *args, **options):
        distinct = defaultdict(set)
        problematic = defaultdict(set)
        for model in (AgendaItem, Proposal, DiscussionPost):
            print(f"Checking {model}")
            for tagitems in (
                model.objects.exclude(tags=[])
                .order_by()
                .values_list("tags", flat=True)
                .distinct()
            ):
                distinct[model].update(tagitems)
            for tag in distinct[model]:
                if not OK_TAG_PATTERN.fullmatch(tag):
                    problematic[model].add(tag)
            if problematic[model]:
                print(f"Found {len(problematic[model])} tags - sample:")
                tags = list(problematic[model])
                shuffle(tags)
                for tag in tags[:30]:
                    _explain(tag)
            else:
                print(f"{problematic[model]} OK!")
        bad_prop_ids = set()
        for tag in (
            Proposal.objects.all()
            .order_by()
            .values_list("prop_id", flat=True)
            .distinct()
        ):
            if not OK_TAG_PATTERN.fullmatch(tag):
                bad_prop_ids.add(tag)
        if bad_prop_ids:
            print(f"Found bad prop_ids - sample:")
            tags = list(bad_prop_ids)
            shuffle(tags)
            for tag in tags[:30]:
                _explain(tag)
        else:
            print("No bad prop_ids")
        # base_tag
        bad_base_tags = set()
        for tag in (
            TextDocument.objects.all()
            .order_by()
            .values_list("base_tag", flat=True)
            .distinct()
        ):
            if not OK_TAG_PATTERN.fullmatch(tag):
                bad_base_tags.add(tag)
        if bad_base_tags:
            print(f"Found bad base_tags - sample:")
            tags = list(bad_base_tags)
            shuffle(tags)
            for tag in tags[:30]:
                _explain(tag)

        else:
            print("No bad base_tags")
        with transaction.atomic():
            # Fix base_tag
            for obj in TextDocument.objects.filter(base_tag__in=bad_base_tags):
                print("== FIXING TextDocument: ")
                _explain(obj.base_tag)
                obj.base_tag = _reformat(obj.base_tag)
                obj.save()
            # Fix body and tags - generic fix
            for model, tags in problematic.items():
                print("== FIXING %s" % model)
                adjusted_tags = 0
                adjusted_prop_ids = 0
                adjusted_body_tags = 0
                for tag in tags:
                    for obj in model.objects.filter(tags__contains=[tag]):
                        # And adjust props specifically - when saving, tag will be adjusted
                        if model is Proposal:
                            if obj.prop_id in bad_prop_ids:
                                if obj.prop_id in obj.tags:
                                    # Will be re-added later
                                    obj.tags.remove(obj.prop_id)
                                adjusted_prop_ids += 1
                                obj.prop_id = _reformat(obj.prop_id)
                        # Regular tag field
                        new_tags = set()  # To remove duplicates
                        for objtag in obj.tags:
                            if OK_TAG_PATTERN.fullmatch(objtag):
                                new_tags.add(objtag)
                            else:
                                new_tags.add(_reformat(objtag))
                                adjusted_tags += 1
                        obj.tags = sorted(new_tags)
                        # Body tags - this will fetch all problematic tags, but it's a better solution and avoids missing anything
                        soup = BeautifulSoup(obj.body, features="lxml")
                        replace_sections = []
                        for hit in soup.find_all(
                            name="span",
                            attrs={"data-denotation-char": "#"},
                        ):
                            body_tag = hit.get("data-id")
                            if not OK_TAG_PATTERN.fullmatch(objtag):
                                adjusted_body_tags += 1
                                replace_sections.append((hit, body_tag))
                        if replace_sections:
                            print("TAG fix for object %s" % obj)
                            for hit, body_tag in replace_sections:
                                reformatted_tag = _reformat(body_tag)
                                obj.body = obj.body.replace(
                                    str(hit), mk_hashtag(reformatted_tag)
                                )
                                _explain(body_tag)
                        obj.save()
                print(
                    f"=== {model}: regular: {adjusted_tags} - body: {adjusted_body_tags} - prop_id {adjusted_prop_ids}"
                )
            if options["commit"]:
                print("Saving...")
            else:
                print("Aborting...")
                transaction.set_rollback(True)
        print("Done")

        # Search should be something like: '<span class="mention" data-denotation-char="#" data-id="kicki-andersson-2 \n"'
        # But ut hela sektionen som börjar med: data-id="kicki-andersson-2 \n" typ med mk_tag?
        # <span class="mention" data-denotation-char="#" data-id="kicki-andersson-2 \n" data-index="0" data-value="kicki-andersson-2 \n">\ufeff<span contenteditable="false"><span class="ql-mention-denotation-char">#</span>kicki-andersson-2 \n</span>\ufeff</span>
        # Checking prop_id and base_tag
