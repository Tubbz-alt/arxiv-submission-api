"""Tests for :mod:`api.controllers`."""

from unittest import TestCase, mock
import json
from datetime import datetime
from werkzeug.exceptions import BadRequest, InternalServerError, NotFound
from pytz import UTC
from arxiv.integration.api import status
from arxiv.submission.domain import User, Submission, Author, Client
from arxiv.submission import CreateSubmission, SaveError, \
    InvalidEvent, NoSuchSubmission, SetPrimaryClassification, \
    SetUploadPackage, SetAuthors, SetTitle, SetAbstract, SetDOI, \
    SetMSCClassification, SetACMClassification, SetJournalReference,  \
    SetComments
from metadata.controllers import submission


def preserve_exceptions_and_events(mock_events):
    """Add real exceptions back to the mock."""
    mock_events.SaveError = SaveError
    mock_events.InvalidEvent = InvalidEvent
    mock_events.NoSuchSubmission = NoSuchSubmission
    mock_events.SetTitle = SetTitle
    mock_events.SetAbstract = SetAbstract
    mock_events.SetComments = SetComments
    mock_events.SetDOI = SetDOI
    mock_events.SetMSCClassification = SetMSCClassification
    mock_events.SetACMClassification = SetACMClassification
    mock_events.SetJournalReference = SetJournalReference

    mock_events.SetAuthors = SetAuthors
    mock_events.Author = Author
    mock_events.CreateSubmission = CreateSubmission
    mock_events.SetPrimaryClassification = SetPrimaryClassification
    mock_events.SetUploadPackage = SetUploadPackage


class TestCreateSubmission(TestCase):
    """Tests for :func:`.submission.create_submission`."""

    def setUp(self):
        """Create some fake request data."""
        self.agents = {
            'creator': User(1234, 'foo@bar.baz',
                            endorsements=[('astro-ph', 'GA')]),
            'client': Client(5678),
            'proxy': None
        }
        self.token = 'asdf1234'
        self.headers = {}

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_create_submission_with_valid_data(self, mock_events, url_for):
        """Create a submission with valid data."""
        preserve_exceptions_and_events(mock_events)
        url_for.return_value = '/foo/'
        user = User(1234, 'foo@bar.baz')
        mock_events.save.return_value = (
            Submission(creator=user, owner=user, created=datetime.now(UTC)),
            [CreateSubmission(creator=user)]
        )
        data = {
            'primary_classification': {
                'category': 'astro-ph.GA'
            }
        }
        resp, stat, head = submission.create_submission(data, self.headers,
                                                        self.agents,
                                                        self.token)
        call_args, call_kwargs = mock_events.save.call_args

        self.assertIsInstance(call_args[0], CreateSubmission,
                              "Should pass a CreateSubmission first")
        self.assertIsInstance(call_args[1], SetPrimaryClassification,
                              "Should pass a SetPrimaryClassification")
        self.assertEqual(stat, status.CREATED,
                         "Should return 201 Created when submission is"
                         " successfully created.")
        self.assertIn('Location', head, "Should include a Location header.")

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_create_submission_with_invalid_data(self, mock_events, url_for):
        """Trying to create a submission with invalid data throws exception."""
        preserve_exceptions_and_events(mock_events)
        url_for.return_value = '/foo/'
        data = {
            'metadata': 'bad value',
        }
        with self.assertRaises(BadRequest):
            submission.create_submission(data, self.headers, self.agents,
                                         self.token)

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_create_submission_with_db_down(self, mock_events, url_for):
        """An internal server error is raised when the database is down."""
        url_for.return_value = '/foo/'
        mock_events.save.side_effect = SaveError
        preserve_exceptions_and_events(mock_events)
        data = {
            'primary_classification': {
                'category': 'astro-ph'
            }
        }
        with self.assertRaises(InternalServerError):
            submission.create_submission(data, self.headers, self.agents,
                                         self.token)

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_create_submission_with_invalid_event(self, mock_events, url_for):
        """A Bad Request error is raised on an invalid event."""
        url_for.return_value = '/foo/'

        def raise_invalid_event(*events, **kwargs):
            raise InvalidEvent(
                CreateSubmission(creator=self.agents['creator']),
                'foo'
            )

        mock_events.save.side_effect = raise_invalid_event
        preserve_exceptions_and_events(mock_events)
        data = {
            'primary_classification': {
                'category': 'astro-ph'
            }
        }
        with self.assertRaises(BadRequest):
            submission.create_submission(data, self.headers, self.agents,
                                         self.token)


class TestUpdateSubmission(TestCase):
    """Tests for :func:`.submission.update_submission`."""

    def setUp(self):
        """Create some fake request data."""
        self.agents = {
            'creator': User(1234, 'foo@bar.baz',
                            endorsements=[('astro-ph', 'GA')]),
            'client': Client(5678),
            'proxy': None
        }
        self.token = 'asdf1234'
        self.headers = {}

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_update_submission_with_valid_data(self, mock_events, url_for):
        """Update a submission with valid data."""
        preserve_exceptions_and_events(mock_events)
        url_for.return_value = '/foo/'
        user = User(1234, 'foo@bar.baz')
        mock_events.save.return_value = (
            Submission(creator=user, owner=user, created=datetime.now(UTC)),
            [CreateSubmission(creator=user),
             SetTitle(creator=user, title='foo title')]
        )
        data = {
            'metadata': {
                'title': 'foo title',
                'authors': [
                    {
                        'forename': 'Jane',
                        'surname': 'Doe',
                        'email': 'jane@doe.com'
                    }
                ]
             }
        }
        resp, stat, head = submission.update_submission(data, self.headers,
                                                        self.agents,
                                                        self.token, 1)
        self.assertEqual(stat, status.OK,
                         "Should return 200 OK when submission is"
                         " successfully updated.")
        self.assertIn('Location', head, "Should include a Location header.")
        call_args, call_kwargs = mock_events.save.call_args

        self.assertIsInstance(call_args[0], SetTitle,
                              "Should pass a SetTitle")
        self.assertIsInstance(call_args[1], SetAuthors,
                              "Should pass an SetAuthors")

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_update_nonexistant_submission(self, mock_events, url_for):
        """Trying to update a nonexistant submission throws exception."""
        preserve_exceptions_and_events(mock_events)
        mock_events.save.side_effect = NoSuchSubmission
        url_for.return_value = '/foo/'
        data = {
            'metadata': {
                'title': 'foo title'
             }
        }
        with self.assertRaises(NotFound):
            submission.update_submission(data, self.headers, self.agents,
                                         self.token, 1)

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_update_submission_with_invalid_data(self, mock_events, url_for):
        """Trying to update a submission with invalid data throws exception."""
        preserve_exceptions_and_events(mock_events)
        url_for.return_value = '/foo/'
        data = {
            'metadata': 'bad value',
        }
        with self.assertRaises(BadRequest):
            submission.update_submission(data, self.headers, self.agents,
                                         self.token, 1)

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_update_submission_with_db_down(self, mock_events, url_for):
        """An internal server error is raised when the database is down."""
        url_for.return_value = '/foo/'
        mock_events.save.side_effect = SaveError
        preserve_exceptions_and_events(mock_events)
        data = {
            'primary_classification': {
                'category': 'astro-ph'
            }
        }
        with self.assertRaises(InternalServerError):
            submission.update_submission(data, self.headers, self.agents,
                                         self.token, 1)

    @mock.patch('metadata.controllers.submission.url_for')
    @mock.patch('metadata.controllers.submission.ev')
    def test_update_submission_with_invalid_event(self, mock_events, url_for):
        """A Bad Request is raised on an invalid event."""
        url_for.return_value = '/foo/'
        preserve_exceptions_and_events(mock_events)

        def raise_invalid_event(*events, **kwargs):
            raise InvalidEvent(
                CreateSubmission(creator=self.agents['creator']),
                'foo'
            )

        mock_events.save.side_effect = raise_invalid_event
        data = {
            'primary_classification': {
                'category': 'astro-ph'
            }
        }
        with self.assertRaises(BadRequest):
            submission.update_submission(data, self.headers, self.agents,
                                         self.token, 1)


class TestGetSubmission(TestCase):
    """Tests for :func:`.submission.get_submission`."""

    @mock.patch('metadata.controllers.submission.ev')
    def test_get_submission(self, mock_events):
        """Should return a JSON-serializable dict if submisison exists."""
        preserve_exceptions_and_events(mock_events)
        user = User(1234, 'foo@bar.baz')
        mock_events.load.return_value = (
            Submission(creator=user, owner=user, created=datetime.now(UTC)),
            [CreateSubmission(creator=user)]
        )
        content, status_code, headers = submission.get_submission(1)
        self.assertEqual(mock_events.load.call_count, 1,
                         "Should call load() in the events core package")
        self.assertEqual(status_code, status.OK,
                         "Should return 200 OK")
        self.assertIsInstance(content, dict, "Should return a dict")
        try:
            json.dumps(content)
        except Exception:
            self.fail("Content should be JSON-serializable.")

    @mock.patch('metadata.controllers.submission.ev')
    def test_get_nonexistant_submission(self, mock_events):
        """Should raise NotFound if the submission does not exist."""
        preserve_exceptions_and_events(mock_events)
        mock_events.load.side_effect = NoSuchSubmission
        with self.assertRaises(NotFound):
            submission.get_submission(1)
