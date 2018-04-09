"""Controllers for the metadata API."""

import json
from functools import wraps
from datetime import datetime
import copy
from arxiv.base import logging
from typing import Tuple, List, Callable, Optional

from flask import url_for, current_app
from werkzeug.exceptions import NotFound, BadRequest, InternalServerError

from arxiv import status
from events.domain.agent import Agent, agent_factory, System
from events.domain import Event
from events.domain.submission import Submission, Classification, License, \
    SubmissionMetadata
import events as ev

from . import util

logger = logging.getLogger(__name__)


Response = Tuple[dict, int, dict]


def _get_agents(headers: dict, user_data: dict, client_data: dict) \
        -> Tuple[Agent, Agent, Optional[Agent]]:
    user = ev.User(
        native_id=user_data['user_id'],
        email=user_data['email']
    )
    client = ev.Client(native_id=client_data['client_id'])
    on_behalf_of = headers.get('X-On-Behalf-Of')
    if on_behalf_of is not None:
        proxy = user
        user = ev.User(on_behalf_of, '', '')
    else:
        proxy = None
    return user, client, proxy


@util.validate_request('schema/resources/submission.json')
def create_submission(data: dict, headers: dict, user_data: dict,
                      client_data: dict, token: str) -> Response:
    """
    Create a new submission.

    Implements the hook for :meth:`sword.SWORDCollection.add_submission`.

    Parameters
    ----------
    data : dict
        Deserialized compact JSON-LD document.
    headers : dict
        Request headers from the client.

    Returns
    -------
    dict
        Response data.
    int
        HTTP status code.
    dict
        Headers to add to the response.
    """
    logger.debug('Received request to create submission')
    user, client, proxy = _get_agents(headers, user_data, client_data)
    logger.debug(f'User: {user}; client: {client}, proxy: {proxy}')
    try:
        submission, events = ev.save(
            ev.CreateSubmission(creator=user, client=client, proxy=proxy),
            *_update_submission(data, user, client, proxy)
        )
    except ev.InvalidEvent as e:
        raise InternalServerError(str(e)) from e
    except ev.SaveError as e:
        raise InternalServerError('Problem interacting with database: %s' % str(e)) from e
    except Exception as e:
        logger.error('Unhandled exception: (%s) %s', str(type(e)), str(e))
        raise InternalServerError('Encountered unhandled exception') from e

    response_headers = {
        'Location': url_for('submission.get_submission',
                            submission_id=submission.submission_id)
    }
    return submission.to_dict(), status.HTTP_201_CREATED, response_headers


def get_submission(submission_id: str, user: Optional[str] = None,
                   client: Optional[str] = None,
                   token: Optional[str] = None) -> Response:
    """Retrieve the current state of a submission."""
    try:
        submission, events = ev.load(submission_id)
    except ev.NoSuchSubmission as e:
        raise NotFound('Submission not found') from e
    except Exception as e:
        logger.error('Unhandled exception: (%s) %s', str(type(e)), str(e))
        raise InternalServerError('Encountered unhandled exception') from e
    return submission.to_dict(), status.HTTP_200_OK, {}


@util.validate_request('schema/resources/submission.json')
def update_submission(data: dict, headers: dict, user_data: dict,
                      client_data: dict, token: str, submission_id: str) \
        -> Response:
    """Update the submission."""
    user, client, proxy = _get_agents(headers, user_data, client_data)
    try:
        submission, events = ev.save(
            *_update_submission(data, user, client, proxy),
            submission_id=submission_id
        )
    except ev.NoSuchSubmission as e:
        raise NotFound(f"No submission found with id {submission_id}")
    except ev.InvalidEvent as e:
        raise InternalServerError(str(e)) from e
    except ev.SaveError as e:
        raise InternalServerError('Problem interacting with database') from e
    except Exception as e:
        logger.error('Unhandled exception: (%s) %s', str(type(e)), str(e))
        raise InternalServerError('Encountered unhandled exception') from e

    response_headers = {
        'Location': url_for('submit.get_submission', creator=user,
                            submission_id=submission.submission_id)
    }
    return submission.to_dict(), status.HTTP_200_OK, response_headers


def _update_submission(data: dict, creator: Agent, client: Agent,
                       proxy: Optional[Agent] = None) -> List[Event]:
    """
    Generate :class:`.ev.Event`(s) to update a :class:`Submission`.

    Parameters
    ----------
    data : dict
    creator : :class:`.Agent`
    client : :class:`.Agent`
    proxy : :class:`.Agent`

    Returns
    -------
    list

    """
    # Since these are used in all Event instantiations, it's convenient to
    # pack these together.
    agents = dict(creator=creator, client=client, proxy=proxy)

    new_events = []
    if 'submitter_is_author' in data:
        new_events.append(
            ev.AssertAuthorship(
                **agents,
                submitter_is_author=data['submitter_is_author']
            )
        )
    if 'license' in data:
        new_events.append(
            ev.SelectLicense(
                **agents,
                license_name=data['license'].get('name'),
                license_uri=data['license']['uri']
            )
        )

    if 'submitter_accepts_policy' in data and data['submitter_accepts_policy']:
        new_events.append(ev.AcceptPolicy(**agents))

    # Generate both primary and secondary classifications.
    if 'primary_classification' in data:
        category = data['primary_classification']['category']
        new_events.append(
            ev.SetPrimaryClassification(**agents, category=category)
        )

    for classification_datum in data.get('secondary_classification', []):
        category = classification_datum['category']
        new_events.append(
            ev.AddSecondaryClassification(**agents, category=category)
        )

    if 'metadata' in data:
        # Most of this could be in a list comprehension, but it may help to
        # keep this verbose in case we want to intervene on values.
        metadata = []
        for key in ev.UpdateMetadata.FIELDS:
            if key not in data['metadata']:
                continue
            value = data['metadata'][key]
            metadata.append((key, value))
        new_events.append(ev.UpdateMetadata(**agents, metadata=metadata))

        if 'authors' in data['metadata']:
            authors = []
            for i, au in enumerate(data['metadata']['authors']):
                if 'order' not in au:
                    au['order'] = i
                authors.append(ev.Author(**au))
            new_events.append(ev.UpdateAuthors(**agents, authors=authors))
    return new_events
