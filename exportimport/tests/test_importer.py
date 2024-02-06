import os

from django.contrib.auth import get_user_model
from django.test import TestCase

from voteit.discussion.models import DiscussionPost
from voteit.meeting.models import Meeting
from voteit.meeting.roles import ROLE_PARTICIPANT
from voteit.proposal.models import Proposal
from voteit.proposal.workflows import ProposalWf
from voteit_tools.exportimport.schemas import MeetingStructure
from voteit_tools.exportimport.tests import FIXTURES_DIR
from voteit_tools.exportimport.tests import read_fixture

User = get_user_model()


class ImporterTests(TestCase):
    fixtures = ["meeting_test_fixture"]

    @classmethod
    def setUpTestData(cls):
        cls.meeting: Meeting = Meeting.objects.get(pk=1)
        cls.participant = cls.meeting.participants.get(username="participant")

    @property
    def _cut(self):
        from voteit_tools.exportimport.importer import Importer

        return Importer

    def test_collect_users(self):
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting)
        data = MeetingStructure(**import_dict)
        importer.data = data
        importer.collect_users()
        self.assertEqual({"participant@voteit.se": self.participant}, importer.user_map)

    def test_import(self):
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting)
        importer.prepare(import_dict)
        importer.run()
        self.assertEqual({"participant@voteit.se": self.participant}, importer.user_map)
        self.assertEqual(
            {"Hot dogs", "Crisps", "Pickles"},
            set(self.meeting.agenda_items.values_list("title", flat=True)),
        )
        disc = DiscussionPost.objects.filter(tags__contains=["styrelse-1"]).get()
        self.assertEqual(self.participant, disc.author)
        meeting_group = self.meeting.groups.first()
        self.assertEqual("the-hellos", meeting_group.groupid)
        self.assertEqual(meeting_group, disc.meeting_group)
        self.assertEqual({self.participant}, set(meeting_group.members.all()))

    def test_import_with_missing_user_abort(self):
        self.participant.delete()
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting)
        importer.prepare(import_dict)
        with self.assertRaises(User.DoesNotExist) as cm:
            importer.run()
        self.assertEqual(
            "Can't find users with the following data:\nparticipant@voteit.se",
            str(cm.exception),
        )

    def test_import_with_missing_user_create(self):
        self.participant.delete()
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting, missing_user="create")
        importer.prepare(import_dict)
        importer.run()
        participant = User.objects.get(email="participant@voteit.se")
        self.assertEqual("Participant", participant.first_name)
        prop = Proposal.objects.get(prop_id="loeksas-1")
        self.assertEqual(participant, prop.author)

    def test_import_with_missing_user_blank(self):
        self.participant.delete()
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting, missing_user="blank")
        importer.prepare(import_dict)
        importer.run()
        prop = Proposal.objects.get(prop_id="loeksas-1")
        self.assertIsNone(prop.author)

    def test_import_from_file(self):
        importer = self._cut(self.meeting)
        fn = os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml")
        importer.from_file(fn)
        importer.run()
        self.assertTrue(Proposal.objects.get(prop_id="loeksas-1"))

    def test_import_add_participant(self):
        self.meeting.remove_roles(self.participant, ROLE_PARTICIPANT)
        importer = self._cut(self.meeting, add_participants=True)
        fn = os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml")
        importer.from_file(fn)
        importer.run()
        self.assertEqual({ROLE_PARTICIPANT}, self.meeting.get_roles(self.participant))

    def test_import_dont_add_participant(self):
        self.meeting.remove_roles(self.participant, ROLE_PARTICIPANT)
        importer = self._cut(self.meeting, add_participants=False)
        fn = os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml")
        importer.from_file(fn)
        importer.run()
        self.assertEqual(None, self.meeting.get_roles(self.participant))

    def test_clear_ai_states(self):
        importer = self._cut(self.meeting, clear_ai_states=True)
        fn = os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml")
        importer.from_file(fn)
        importer.run()
        self.assertEqual(
            "private", self.meeting.agenda_items.get(title="Pickles").state
        )

    def test_keep_ai_state(self):
        importer = self._cut(self.meeting, clear_ai_states=False)
        fn = os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml")
        importer.from_file(fn)
        importer.run()
        self.assertEqual(
            "upcoming", self.meeting.agenda_items.get(title="Pickles").state
        )

    def test_keep_proposal_states(self):
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting, clear_proposal_states=False)
        importer.prepare(import_dict)
        importer.run()
        prop = Proposal.objects.get(prop_id="loeksas-1")
        self.assertEqual(ProposalWf.APPROVED, prop.state)

    def test_clear_proposal_states(self):
        import_dict = read_fixture("combined_meeting_fixture.yaml")
        importer = self._cut(self.meeting, clear_proposal_states=True)
        importer.prepare(import_dict)
        importer.run()
        prop = Proposal.objects.get(prop_id="loeksas-1")
        self.assertEqual(ProposalWf.PUBLISHED, prop.state)

    def test_len(self):
        importer = self._cut(self.meeting)
        self.assertEqual(0, len(importer))
        importer.from_file(os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml"))
        self.assertEqual(4, len(importer))

    def test_stats(self):
        importer = self._cut(self.meeting)
        importer.from_file(os.path.join(FIXTURES_DIR, "combined_meeting_fixture.yaml"))
        self.assertEqual(
            {
                "agenda_items": 3,
                "diff_proposals": 1,
                "discussion_posts": 2,
                "groups": 1,
                "proposals": 3,
                "text_documents": 1,
            },
            importer.stats().dict(),
        )
