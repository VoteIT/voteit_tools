import csv
import re
from itertools import groupby

import yaml
from django.core.management import BaseCommand
from django.utils.text import slugify
from django.utils.timezone import now

from voteit_tools.exportimport import schemas


class Command(BaseCommand):
    help = "Formatera motioner från Questback"

    def add_arguments(self, parser):
        parser.add_argument("input", help="Input filename")
        parser.add_argument("output", help="Output filename")

    def get_supported_by(self, txt: str) -> bool:
        if txt.startswith("Motionen antagen som egen "):
            return True
        elif txt.startswith("Motionen avslagen av "):
            return False
        raise ValueError(f"Matchar inte kända värden för stöd: '{txt}'")

    def add_paras(self, txt: str) -> str:
        if "<p>" in txt.lower():
            return txt
        txt = txt.strip()
        txt = re.sub(r"(\s*)[\n]{2,}", "</p>\n<p>", txt)
        reformatted = ""
        for row in txt.splitlines():
            row = row.strip()
            if not row.endswith(">"):
                row += "<br/>"
            reformatted += row + "\n"
        txt = "<p>" + reformatted + "</p>"
        txt = txt.replace("<br/>\n</p>", "</p>")
        return re.sub(r"(<br/>\n){2,}", "</p>\n<p>", txt, flags=re.DOTALL)

    def handle(self, *args, **options):
        with open(options["input"], "r") as f:
            raw_data = f.readlines()
        reader = csv.reader(raw_data, delimiter=";")
        header = next(reader)
        print(header)
        motionstext_col = header.index("Motionstext")
        antagen_avslagen_col = header.index("Motionen är antagen/avslagen")
        inskickad_av_col = header.index("Inskickad av")  # En
        forslags_col = header.index("Yrkande")
        motionar_col = header.index(
            "Grupp"
        )  # <- Är egentligen motionär. Ska till brödtexten, kan vara föreningsnamn eller personnamn
        title_col = header.index("Motion")  # Bara en del av titeln, kolla längden!
        topic_col = header.index(
            "Kategorinamn"
        )  # Ska vara tagg och en dagordningspunkt, + kanske ha bokstav i titeln...?
        topic_bokstav_col = header.index("Kategori")
        topic_nummer_col = header.index("Nummer")
        agenda_items = []
        meeting_groups = {}  # GroupID as key
        # FIXME: Titel?
        ENSKILD_MOTIONAR = "enskild"
        meeting_groups[ENSKILD_MOTIONAR] = schemas.MeetingGroupData(
            groupid=ENSKILD_MOTIONAR, title="Enskild motionär", created=now()
        )
        TITLE_LIMIT = 95
        GT_LIMIT = 100
        topic_to_title = {}
        for i, row in enumerate(reader, start=2):  # Headern är borta
            topic_tag = slugify(row[topic_col], allow_unicode=True)
            topic_to_title[topic_tag] = row[topic_col]
            body = row[motionstext_col]
            body += f"\n<h4>Motionär(er)</h4>\n\n{row[motionar_col]}\n"
            body += f"<h4>Inskickad av</h4>\n\n{row[inskickad_av_col]}\n"
            body += f"<h4>Status</h4>\n\n{row[antagen_avslagen_col]}\n"
            body = self.add_paras(body)
            title = row[title_col]
            # ADD num etc
            if len(title) > TITLE_LIMIT:
                print(
                    f"Rad {i} titel concat: '{title[:TITLE_LIMIT]}'\t | \t{title[TITLE_LIMIT:]}"
                )
                title = title[:TITLE_LIMIT]
            title = f"{row[topic_bokstav_col]}{row[topic_nummer_col]} {title}"
            if self.get_supported_by(row[antagen_avslagen_col]):
                groupid = slugify(row[motionar_col])[:GT_LIMIT]
                if groupid not in meeting_groups:
                    if "," in row[motionar_col]:
                        print(
                            f"Rad {i} grupptitel kan vara flera grupper: {row[motionar_col]}"
                        )
                    if len(row[motionar_col]) > GT_LIMIT:
                        print(
                            f"Rad {i} grupptitel concat: '{row[motionar_col][:GT_LIMIT]}'\t | \t{row[motionar_col][GT_LIMIT:]}"
                        )
                    group_title = row[motionar_col][:GT_LIMIT]
                    meeting_groups[groupid] = schemas.MeetingGroupData(
                        groupid=groupid, title=group_title, created=now()
                    )
                meeting_group = groupid
            else:
                meeting_group = ENSKILD_MOTIONAR
            # FIXME:Author?
            proposals = [
                schemas.ProposalData(body=x, meeting_group=meeting_group, created=now())
                for x in row[forslags_col].splitlines()
            ]
            agenda_items.append(
                schemas.AgendaItemData(
                    title=title,
                    body=body,
                    proposals=proposals,
                    tags=[topic_tag],
                    created=now(),
                )
            )
        # Resort agenda items
        resorted_ais = []

        def _sorter(ai_item):
            possible_num = ai_item.title.split(" ")[0][1:]
            if possible_num:
                return int(possible_num)
            return 999

        for k, g in groupby(agenda_items, key=lambda x: x.tags[0]):
            resorted_ais.append(
                schemas.AgendaItemData(title=topic_to_title[k], tags=[k], created=now())
            )
            resorted_ais.extend(sorted(g, key=_sorter))
        meeting_data = schemas.MeetingStructure(
            agenda_items=resorted_ais, groups=list(meeting_groups.values())
        )
        dict_data = meeting_data.dict(exclude_unset=True)
        dict_data["meta"] = {}
        dict_data["meta"]["version"] = 1
        with open(options["output"], "w") as f:
            yaml.dump(dict_data, stream=f)
        self.stdout.write(self.style.SUCCESS("All done!"))
