#!/usr/bin/env python

"""
conference.py -- Udacity conference server-side Python App Engine API;
    uses Google Cloud Endpoints

$Id: conference.py,v 1.25 2014/05/24 23:42:19 wesc Exp wesc $

created by wesc on 2014 apr 21

Extended by Andrew Sychra on 2016 mar 03

"""

__author__ = 'wesc+api@google.com (Wesley Chun)'


from datetime import datetime

import endpoints
from protorpc import messages
from protorpc import message_types
from protorpc import remote

from google.appengine.api import memcache
from google.appengine.api import taskqueue
from google.appengine.ext import ndb

from models import ConflictException
from models import Profile
from models import ProfileMiniForm
from models import ProfileForm
from models import StringMessage
from models import BooleanMessage
from models import Conference
from models import ConferenceForm
from models import ConferenceForms
from models import ConferenceQueryForm
from models import ConferenceQueryForms
from models import TeeShirtSize
from models import Session
from models import SessionForm
from models import SessionForms
from models import confWebSafeKey
from models import SessionByType
from models import WishList
from models import WishListForm

from settings import WEB_CLIENT_ID
from settings import ANDROID_CLIENT_ID
from settings import IOS_CLIENT_ID
from settings import ANDROID_AUDIENCE

from utils import getUserId

EMAIL_SCOPE = endpoints.EMAIL_SCOPE
API_EXPLORER_CLIENT_ID = endpoints.API_EXPLORER_CLIENT_ID
FEATURED_SPEAKER = "Speaker goes here"
MEMCACHE_ANNOUNCEMENTS_KEY = "RECENT_ANNOUNCEMENTS"
ANNOUNCEMENT_TPL = ('Last chance to attend! The following conferences '
                    'are nearly sold out: %s')

# - - - - - - - - - - - - - - - - - - - - - - - - - - - - - -

DEFAULTS = {
    "city": "Default City",
    "maxAttendees": 0,
    "seatsAvailable": 0,
    "topics": [ "Default", "Topic" ],
}

SESS_DEFAULTS = {
    "name": "Topic needs to go here"
}

OPERATORS = {
            'EQ':   '=',
            'GT':   '>',
            'GTEQ': '>=',
            'LT':   '<',
            'LTEQ': '<=',
            'NE':   '!='
            }

FIELDS =    {
            'CITY': 'city',
            'TOPIC': 'topics',
            'MONTH': 'month',
            'MAX_ATTENDEES': 'maxAttendees',
            }

CONF_GET_REQUEST = endpoints.ResourceContainer(
    message_types.VoidMessage,
    websafeConferenceKey=messages.StringField(1),
)

CONF_POST_REQUEST = endpoints.ResourceContainer(
    ConferenceForm,
    websafeConferenceKey=messages.StringField(1),
)










@endpoints.api(name='conference', version='v1', audiences=[ANDROID_AUDIENCE],
    allowed_client_ids=[WEB_CLIENT_ID, API_EXPLORER_CLIENT_ID, ANDROID_CLIENT_ID, IOS_CLIENT_ID],
    scopes=[EMAIL_SCOPE])
class ConferenceApi(remote.Service):
    """Conference API v0.1"""


    # This is mostly a duplicate of the _createConferenceObject in respects to building a parent key for
    # queries that need to be performed later on. Logic for adding a featured speaker to memcache is added
    # below.
    def _createSessionObject(self, request):
        """Create or update Session object, returning SessionForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Session 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        # del data['confWebSafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in SESS_DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])


        # Building the Session parent key to assign it to the specific parent
        p_key = ndb.Key(urlsafe=request.websafeKey)
        c_id = Session.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Session, c_id, parent=p_key)
        data['key'] = c_key

        data['organizerUserId'] = request.organizerUserId = user_id



        # creation of Session & return (modified) SessionForm
        Session(**data).put()

        #This is after the .put() that way the conference is queried with the newly assigned
        #session.
        #Any speaker that now has more than once session will immediately be set as the featured speaker
        sessQ = Session.query(ancestor=p_key)
        discoverFeaturedSpeaker = sessQ.filter(Session.speaker == request.speaker)
        items = 0
        # Person has to speak at least once
        for i in discoverFeaturedSpeaker:
            items += 1
            if items > 1:
                memcache.set(FEATURED_SPEAKER, request.speaker)

        taskqueue.add(params={'email': user.email(),
            'sessionInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    # This is just a modified form of the copyConferenceToForm but for session
    # helper function abstracted away because several endpoint methods will use it.
    def _copySessionToForm(self, sess):
        """Copy relevant fields from Session to SessionForm."""
        sf = SessionForm()
        for field in sf.all_fields():
            setattr(sf, field.name, getattr(sess, field.name))

        sf.check_initialized()
        return sf




# - - - Conference objects - - - - - - - - - - - - - - - - -

    def _copyConferenceToForm(self, conf, displayName):
        """Copy relevant fields from Conference to ConferenceForm."""
        cf = ConferenceForm()
        for field in cf.all_fields():
            if hasattr(conf, field.name):
                # convert Date to date string; just copy others
                if field.name.endswith('Date'):
                    setattr(cf, field.name, str(getattr(conf, field.name)))
                else:
                    setattr(cf, field.name, getattr(conf, field.name))
            elif field.name == "websafeKey":
                setattr(cf, field.name, conf.key.urlsafe())
        if displayName:
            setattr(cf, 'organizerDisplayName', displayName)
        cf.check_initialized()
        return cf


    def _createConferenceObject(self, request):
        """Create or update Conference object, returning ConferenceForm/request."""
        # preload necessary data items
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        if not request.name:
            raise endpoints.BadRequestException("Conference 'name' field required")

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}
        del data['websafeKey']
        del data['organizerDisplayName']

        # add default values for those missing (both data model & outbound Message)
        for df in DEFAULTS:
            if data[df] in (None, []):
                data[df] = DEFAULTS[df]
                setattr(request, df, DEFAULTS[df])

        # convert dates from strings to Date objects; set month based on start_date
        if data['startDate']:
            data['startDate'] = datetime.strptime(data['startDate'][:10], "%Y-%m-%d").date()
            data['month'] = data['startDate'].month
        else:
            data['month'] = 0
        if data['endDate']:
            data['endDate'] = datetime.strptime(data['endDate'][:10], "%Y-%m-%d").date()

        # set seatsAvailable to be same as maxAttendees on creation
        if data["maxAttendees"] > 0:
            data["seatsAvailable"] = data["maxAttendees"]
        # generate Profile Key based on user ID and Conference
        # ID based on Profile key get Conference key from ID
        p_key = ndb.Key(Profile, user_id)
        c_id = Conference.allocate_ids(size=1, parent=p_key)[0]
        c_key = ndb.Key(Conference, c_id, parent=p_key)
        data['key'] = c_key
        data['organizerUserId'] = request.organizerUserId = user_id

        # create Conference, send email to organizer confirming
        # creation of Conference & return (modified) ConferenceForm
        Conference(**data).put()
        taskqueue.add(params={'email': user.email(),
            'conferenceInfo': repr(request)},
            url='/tasks/send_confirmation_email'
        )
        return request


    @ndb.transactional()
    def _updateConferenceObject(self, request):
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # copy ConferenceForm/ProtoRPC Message into dict
        data = {field.name: getattr(request, field.name) for field in request.all_fields()}

        # update existing conference
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        # check that conference exists
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)

        # check that user is owner
        if user_id != conf.organizerUserId:
            raise endpoints.ForbiddenException(
                'Only the owner can update the conference.')

        # Not getting all the fields, so don't create a new object; just
        # copy relevant fields from ConferenceForm to Conference object
        for field in request.all_fields():
            data = getattr(request, field.name)
            # only copy fields where we get data
            if data not in (None, []):
                # special handling for dates (convert string to Date)
                if field.name in ('startDate', 'endDate'):
                    data = datetime.strptime(data, "%Y-%m-%d").date()
                    if field.name == 'startDate':
                        conf.month = data.month
                # write to Conference object
                setattr(conf, field.name, data)
        conf.put()
        prof = ndb.Key(Profile, user_id).get()
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(ConferenceForm, ConferenceForm, path='conference',
            http_method='POST', name='createConference')
    def createConference(self, request):
        """Create new conference."""
        return self._createConferenceObject(request)



# - - - - - - - - - - Task 1 - - - - - - - - - - - - - - - - - - - -


    """
    The session and speaker design:

         The session is it's own entity, it is very similar to a conference and is actually designed to
         be a child of a conference and that's how it hold a distinction to it. A session can only
         be assigned to once conference.

         The speaker is simply a string value inside of the session. I decided to keep it very simple.
    """

# Setup to return an array of all Sessions this person talks at, just the key is needed.
    @endpoints.method(StringMessage, SessionForms,
            path='getConferenceSessions',
            http_method='POST', name='getConferenceSessions')
    # confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
    def getConferenceSessions(self, request):
        """Return sessions based on conference key."""


        sess = Session.query(ancestor=ndb.Key(urlsafe=request.data))
        # code to view results in logs
        # speaking = sess.filter(Session.typeOfSession == request.type)
        # speaking = sess.filter(Session.query(ancestor=ndb.Key(urlsafe=request.websafeKey)))
        # for q in sess:
        #     print q
        #     print " below this another one:"

        # return message_types.VoidMessage
        return SessionForms(
            items=[self._copySessionToForm(sf) for sf in sess]
        )



    # Setup to return an array of all Sessions this person talks at, just the key is needed.
    @endpoints.method(SessionByType, SessionForms,
            path='getConferenceSessionsByType',
            http_method='POST', name='getConferenceSessionsByType')
    # confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
    def getConferenceSessionsByType(self, request):
        """Return conferences set by a specific type, make sure whatever you put in for the Session Type
           you write verbatim into the input."""


        sess = Session.query(ancestor=ndb.Key(urlsafe=request.websafeKey))
        speaking = sess.filter(Session.typeOfSession == request.type)

        return SessionForms(
            items=[self._copySessionToForm(sf) for sf in speaking]
        )


    # Setup to return an array of all Sessions this person talks at, just the key is needed.
    @endpoints.method(StringMessage, SessionForms,
            path='getSessionsBySpeaker',
            http_method='POST', name='getSessionsBySpeaker')
    def getSessionsSpeaker(self, request):
        """Return all Sessions a speaker is currently engagned in at a conference."""


        # create ancestor query for all key matches for this user
        sess = Session.query()
        speaking = sess.filter(Session.speaker == request.data)


        # returns all Sessions
        return SessionForms(
            items=[self._copySessionToForm(sf) for sf in speaking]
        )


    ###########createSession, modify this later so 2nd argument is websafeConferenceKey
    @endpoints.method(SessionForm, SessionForm, path='session',
                http_method='POST', name='createSession')
    def createSession(self, request):
        """Create new session."""
        return self._createSessionObject(request)



# - - - - - - - - - - Task 2 - - - - - - - - - - - - - - - - - - - -

    """
    Wishlists can be added acrose all conferences, even those the user is not registered for.

    """

# Wishlist keys will be children of Sessoins with the users Profile and userid added.
    @endpoints.method(WishListForm, StringMessage,
            path='addSessionToWishlist',
            http_method='POST', name='addSessionToWishlist')
    def addSessionToWishlist(self, request):
        """Adds conference to users wishlist."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)


        p_key = ndb.Key(urlsafe=request.sessionKey)
        print p_key

        wishItem = WishList(parent=p_key)

        #Assign the wishlist item to have both a sessionkey to get he session and the user_id to correctly call it
        #back uniquely to that user.
        wishItem.sessionKey = request.sessionKey
        wishItem.userID = user_id

        wishItem.put()

        # This is just setting up the message to return to the user
        websafeKey = StringMessage()
        websafeKey.data = "Successfully added to wishlist: " + request.sessionKey

        testQ = WishList.query()

        #Just return the message confirming that the session was added to the wishlist
        return websafeKey




    @endpoints.method(message_types.VoidMessage, SessionForms,
            path='getSessionsInWishlist',
            http_method='POST', name='getSessionsInWishlist')
    def getSessionsInWishlist(self, request):
        """Return sessions in users wishlist."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        key_array = []
        print user_id



        wlist = WishList.query()
        filtered = wlist.filter(WishList.userID == user_id)
        for w in filtered:
            key_array.append(w.sessionKey) #loop through this as urlsafekey



        # array to hold all ancestor keys for sessions in the wishlist to call all the relevant sessions
        items = []

        for key in key_array:

            item = WishList.query(ancestor=ndb.Key(urlsafe=key))
            print item.ancestor
            items.append(item.ancestor)

        # Calls specific session in query from all the encoded keys in the key_array
        Forms = []
        for key in key_array:
            item = ndb.Key(urlsafe=key)
            print item
            print "another item"
            session = item.get()
            if session:
                Forms.append(self._copySessionToForm(session))

        # return all the sessions in the wishlist
        return SessionForms(items=Forms)





    # Put in the Session Key to delete the session for the wishlist
    @endpoints.method(StringMessage, StringMessage,
                path='deleteSessionInWishlist',
                http_method='POST', name='deleteSessionInWishlist')
    def deleteSessionInWishlist(self, request):
        """Delete sessions in users wishlist."""
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # item = WishList.query(ndb.Key(urlsafe=request.sessionKey))
        # item.delete()


        # key = ndb.Key(urlsafe=request.data)
        # print key
        # print "I just used the key"
        testQ = WishList.query()
        filtered = testQ.filter(WishList.sessionKey == request.data)
        # print filtered
        # p = testQ.filter(WishList.sessionKey == request.data and WishList.userID == user_id)
        for t in filtered:
            t.key.delete()

        websafeKey = StringMessage()
        # Fedback to user, confirming item in wishlist was deleted.
        websafeKey.data = "wishlist item deleted"

        return websafeKey


# - - - - - - - - - - Task 3 - - - - - - - - - - - - - - - - - - - -


    # This retreives all the sessions (without regard for conference) before the noon hour and includes those that have no specified time
    # It was easy enough to design it, simply like getting sessions of a type but just using start time
    # and then filtering with a less than before 12
    @endpoints.method(message_types.VoidMessage, SessionForms,
                path='getAllMorningSessions',
                http_method='POST', name='getAllMorningSessions')
    def getAllMorningSessions(self, request):
        """Returns all sessions in all conferences before 12pm."""

        # create ancestor query for all key matches for this user
        sess = Session.query()
        speaking = sess.filter(Session.startTime < 12)
        for q in speaking:
            print q
            print " below this another one:"

        # return message_types.VoidMessage
        return SessionForms(
            items=[self._copySessionToForm(sf) for sf in speaking]
        )


    # Same setup as the above endpoint except using greater than or equal to 12 o'clock, based on 1-24 hours
    # military time essentially
    @endpoints.method(message_types.VoidMessage, SessionForms,
                path='getAllAfternoonSessions',
                http_method='POST', name='getAllAfternoonSessions')
    def getAllAfternoonSessions(self, request):
        """Returns all sessions in all conferences after 12pm."""

        sess = Session.query()
        speaking = sess.filter(Session.startTime >= 12)
        for q in speaking:
            print q
            print " below this another one:"

        # return message_types.VoidMessage
        return SessionForms(
            items=[self._copySessionToForm(sf) for sf in speaking]
        )



    # Same as the time filter but just added an "and" statement. Assuming Workshops are assigned with "Workshop" as the
    # Session.type, than it's simply a matter of avoiding all sessions with that as the text.
    @endpoints.method(message_types.VoidMessage, SessionForms,
                path='getNoneWorkshopsBefore7',
                http_method='POST', name='getNoneWorkshopsBefore7')
    def getNoneWorkshopsBefore7(self, request):
        """Returns all sessions in all conferences before 7pm and that are not a 'Workshop'."""

        sess = Session.query()
        speaking = sess.filter(Session.startTime < 19 and Session.typeOfSession != "Workshop")
        for q in speaking:
            print q
            print " below this another one:"

        # return message_types.VoidMessage
        return SessionForms(
            items=[self._copySessionToForm(sf) for sf in speaking]
        )

# - - - - - - - - - - Task 4 - - - - - - - - - - - - - - - - - - - -


    # Simply calls and returns the value stored in memcache, logic is set during a _createSession where
    # works for the most immediately added session to the conference that meets the criteria.
    # the speaker will have to be assigned either his 2nd or greater number of gigs for the conference.
    # This is based on the getAnnouncement endpoint and function call
    # Setting of the key speaker is all done in the createSession endpoint where
    # anyone who is assigned 2 or more speaking gigs will immediately be called the featured speaker.
    @endpoints.method(message_types.VoidMessage, StringMessage,
        path='conference/getFeaturedSpeaker',
        http_method='GET', name='getFeaturedSpeaker')
    def getFeaturedSpeaker(self, request):
        """Retrieves speaker from memcache."""
        return StringMessage(data=memcache.get(FEATURED_SPEAKER) or "")



# - - - - - - - - - - end of user-defined tasks - - - - - - - - - - - - - - - - - - - -




    @endpoints.method(CONF_POST_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='PUT', name='updateConference')
    def updateConference(self, request):
        """Update conference w/provided fields & return w/updated info."""
        return self._updateConferenceObject(request)


    @endpoints.method(CONF_GET_REQUEST, ConferenceForm,
            path='conference/{websafeConferenceKey}',
            http_method='GET', name='getConference')
    def getConference(self, request):
        """Return requested conference (by websafeConferenceKey)."""
        # get Conference object from request; bail if not found
        conf = ndb.Key(urlsafe=request.websafeConferenceKey).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % request.websafeConferenceKey)
        prof = conf.key.parent().get()
        # return ConferenceForm
        return self._copyConferenceToForm(conf, getattr(prof, 'displayName'))


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='getConferencesCreated',
            http_method='POST', name='getConferencesCreated')
    def getConferencesCreated(self, request):
        """Return conferences created by user."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')
        user_id = getUserId(user)

        # create ancestor query for all key matches for this user
        confs = Conference.query(ancestor=ndb.Key(Profile, user_id))
        prof = ndb.Key(Profile, user_id).get()
        # return set of ConferenceForm objects per Conference
        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, getattr(prof, 'displayName')) for conf in confs]
        )



    def _getQuery(self, request):
        """Return formatted query from the submitted filters."""
        q = Conference.query()
        inequality_filter, filters = self._formatFilters(request.filters)

        # If exists, sort on inequality filter first
        if not inequality_filter:
            q = q.order(Conference.name)
        else:
            q = q.order(ndb.GenericProperty(inequality_filter))
            q = q.order(Conference.name)

        for filtr in filters:
            if filtr["field"] in ["month", "maxAttendees"]:
                filtr["value"] = int(filtr["value"])
            formatted_query = ndb.query.FilterNode(filtr["field"], filtr["operator"], filtr["value"])
            q = q.filter(formatted_query)
        return q


    def _formatFilters(self, filters):
        """Parse, check validity and format user supplied filters."""
        formatted_filters = []
        inequality_field = None

        for f in filters:
            filtr = {field.name: getattr(f, field.name) for field in f.all_fields()}

            try:
                filtr["field"] = FIELDS[filtr["field"]]
                filtr["operator"] = OPERATORS[filtr["operator"]]
            except KeyError:
                raise endpoints.BadRequestException("Filter contains invalid field or operator.")

            # Every operation except "=" is an inequality
            if filtr["operator"] != "=":
                # check if inequality operation has been used in previous filters
                # disallow the filter if inequality was performed on a different field before
                # track the field on which the inequality operation is performed
                if inequality_field and inequality_field != filtr["field"]:
                    raise endpoints.BadRequestException("Inequality filter is allowed on only one field.")
                else:
                    inequality_field = filtr["field"]

            formatted_filters.append(filtr)
        return (inequality_field, formatted_filters)


    @endpoints.method(ConferenceQueryForms, ConferenceForms,
            path='queryConferences',
            http_method='POST',
            name='queryConferences')
    def queryConferences(self, request):
        """Query for conferences."""
        conferences = self._getQuery(request)

        # need to fetch organiser displayName from profiles
        # get all keys and use get_multi for speed
        organisers = [(ndb.Key(Profile, conf.organizerUserId)) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return individual ConferenceForm object per Conference
        return ConferenceForms(
                items=[self._copyConferenceToForm(conf, names[conf.organizerUserId]) for conf in \
                conferences]
        )







# - - - Profile objects - - - - - - - - - - - - - - - - - - -

    def _copyProfileToForm(self, prof):
        """Copy relevant fields from Profile to ProfileForm."""
        # copy relevant fields from Profile to ProfileForm
        pf = ProfileForm()
        for field in pf.all_fields():
            if hasattr(prof, field.name):
                # convert t-shirt string to Enum; just copy others
                if field.name == 'teeShirtSize':
                    setattr(pf, field.name, getattr(TeeShirtSize, getattr(prof, field.name)))
                else:
                    setattr(pf, field.name, getattr(prof, field.name))
        pf.check_initialized()
        return pf


    def _getProfileFromUser(self):
        """Return user Profile from datastore, creating new one if non-existent."""
        # make sure user is authed
        user = endpoints.get_current_user()
        if not user:
            raise endpoints.UnauthorizedException('Authorization required')

        # get Profile from datastore
        user_id = getUserId(user)
        p_key = ndb.Key(Profile, user_id)
        profile = p_key.get()
        # create new Profile if not there
        if not profile:
            profile = Profile(
                key = p_key,
                displayName = user.nickname(),
                mainEmail= user.email(),
                teeShirtSize = str(TeeShirtSize.NOT_SPECIFIED),
            )
            profile.put()

        return profile      # return Profile


    def _doProfile(self, save_request=None):
        """Get user Profile and return to user, possibly updating it first."""
        # get user Profile
        prof = self._getProfileFromUser()

        # if saveProfile(), process user-modifyable fields
        if save_request:
            for field in ('displayName', 'teeShirtSize'):
                if hasattr(save_request, field):
                    val = getattr(save_request, field)
                    if val:
                        setattr(prof, field, str(val))
                        #if field == 'teeShirtSize':
                        #    setattr(prof, field, str(val).upper())
                        #else:
                        #    setattr(prof, field, val)
                        prof.put()

        # return ProfileForm
        return self._copyProfileToForm(prof)


    @endpoints.method(message_types.VoidMessage, ProfileForm,
            path='profile', http_method='GET', name='getProfile')
    def getProfile(self, request):
        """Return user profile."""
        return self._doProfile()


    @endpoints.method(ProfileMiniForm, ProfileForm,
            path='profile', http_method='POST', name='saveProfile')
    def saveProfile(self, request):
        """Update & return user profile."""
        return self._doProfile(request)


# - - - Announcements - - - - - - - - - - - - - - - - - - - -

    @staticmethod
    def _cacheAnnouncement():
        """Create Announcement & assign to memcache; used by
        memcache cron job & putAnnouncement().
        """
        confs = Conference.query(ndb.AND(
            Conference.seatsAvailable <= 5,
            Conference.seatsAvailable > 0)
        ).fetch(projection=[Conference.name])

        if confs:
            # If there are almost sold out conferences,
            # format announcement and set it in memcache
            announcement = ANNOUNCEMENT_TPL % (
                ', '.join(conf.name for conf in confs))
            memcache.set(MEMCACHE_ANNOUNCEMENTS_KEY, announcement)
        else:
            # If there are no sold out conferences,
            # delete the memcache announcements entry
            announcement = ""
            memcache.delete(MEMCACHE_ANNOUNCEMENTS_KEY)

        return announcement


    @endpoints.method(message_types.VoidMessage, StringMessage,
            path='conference/announcement/get',
            http_method='GET', name='getAnnouncement')
    def getAnnouncement(self, request):
        """Return Announcement from memcache."""
        return StringMessage(data=memcache.get(MEMCACHE_ANNOUNCEMENTS_KEY) or "")


# - - - Registration - - - - - - - - - - - - - - - - - - - -


    @ndb.transactional(xg=True)
    def _conferenceRegistration(self, request, reg=True):
        """Register or unregister user for selected conference."""
        retval = None
        prof = self._getProfileFromUser() # get user Profile

        # check if conf exists given websafeConfKey
        # get conference; check that it exists
        wsck = request.websafeConferenceKey
        conf = ndb.Key(urlsafe=wsck).get()
        if not conf:
            raise endpoints.NotFoundException(
                'No conference found with key: %s' % wsck)

        # register
        if reg:
            # check if user already registered otherwise add
            if wsck in prof.conferenceKeysToAttend:
                raise ConflictException(
                    "You have already registered for this conference")

            # check if seats avail
            if conf.seatsAvailable <= 0:
                raise ConflictException(
                    "There are no seats available.")

            # register user, take away one seat
            prof.conferenceKeysToAttend.append(wsck)
            conf.seatsAvailable -= 1
            retval = True

        # unregister
        else:
            # check if user already registered
            if wsck in prof.conferenceKeysToAttend:

                # unregister user, add back one seat
                prof.conferenceKeysToAttend.remove(wsck)
                conf.seatsAvailable += 1
                retval = True
            else:
                retval = False

        # write things back to the datastore & return
        prof.put()
        conf.put()
        return BooleanMessage(data=retval)



    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='conferences/attending',
            http_method='GET', name='getConferencesToAttend')
    def getConferencesToAttend(self, request):
        """Get list of conferences that user has registered for."""
        prof = self._getProfileFromUser() # get user Profile
        conf_keys = [ndb.Key(urlsafe=wsck) for wsck in prof.conferenceKeysToAttend]
        conferences = ndb.get_multi(conf_keys)

        # get organizers
        organisers = [ndb.Key(Profile, conf.organizerUserId) for conf in conferences]
        profiles = ndb.get_multi(organisers)

        # put display names in a dict for easier fetching
        names = {}
        for profile in profiles:
            names[profile.key.id()] = profile.displayName

        # return set of ConferenceForm objects per Conference
        return ConferenceForms(items=[self._copyConferenceToForm(conf, names[conf.organizerUserId])\
         for conf in conferences]
        )


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='POST', name='registerForConference')
    def registerForConference(self, request):
        """Register user for selected conference."""
        return self._conferenceRegistration(request)


    @endpoints.method(CONF_GET_REQUEST, BooleanMessage,
            path='conference/{websafeConferenceKey}',
            http_method='DELETE', name='unregisterFromConference')
    def unregisterFromConference(self, request):
        """Unregister user for selected conference."""
        return self._conferenceRegistration(request, reg=False)


    @endpoints.method(message_types.VoidMessage, ConferenceForms,
            path='filterPlayground',
            http_method='GET', name='filterPlayground')
    def filterPlayground(self, request):
        """Filter Playground"""
        q = Conference.query()
        # field = "city"
        # operator = "="
        # value = "London"
        # f = ndb.query.FilterNode(field, operator, value)
        # q = q.filter(f)
        q = q.filter(Conference.city=="London")
        q = q.filter(Conference.topics=="Medical Innovations")
        q = q.filter(Conference.month==6)

        return ConferenceForms(
            items=[self._copyConferenceToForm(conf, "") for conf in q]
        )







api = endpoints.api_server([ConferenceApi]) # register API
