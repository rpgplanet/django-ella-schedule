# -*- coding: utf-8 -*-
import datetime

from django.contrib.contenttypes import generic
from django.db import models
from django.db.models import Q
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.core.urlresolvers import reverse
from django.template.defaultfilters import date
from django.utils.translation import ugettext, ugettext_lazy as _

from dateutil import rrule

from ella.core.models import Publishable

from ellaschedule.models.rules import Rule
from ellaschedule.models.calendars import Calendar
from ellaschedule.utils import OccurrenceReplacer

class EventManager(models.Manager):

    def get_for_object(self, content_object, distinction=None, inherit=True):
        return EventRelation.objects.get_events_for_object(content_object, distinction, inherit)

class Event(Publishable):
    '''
    This model stores meta data for a date.  You can relate this data to many
    other models.
    '''
    start = models.DateTimeField(_("start"), null=True, blank=True)
    end = models.DateTimeField(_("end"), null=True, blank=True, help_text=_("The end time must be later than the start time."))
    creator = models.ForeignKey(User, null = True, verbose_name=_("creator"))
    created_on = models.DateTimeField(_("created on"), default = datetime.datetime.now)
    rule = models.ForeignKey(Rule, null = True, blank = True, verbose_name=_("rule"), help_text=_("Select '----' for a one time only event."))
    end_recurring_period = models.DateTimeField(_("end recurring period"), null = True, blank = True, help_text=_("This date is ignored for one time only events."))
    calendar = models.ForeignKey(Calendar, blank=True)
    parent_event = models.ForeignKey('self', null=True, blank=True)
    place = models.CharField(_("place"), max_length=255, null=True, blank=True, help_text=_("Where is this event occurring"))
    objects = EventManager()

    class Meta:
        verbose_name = _('event')
        verbose_name_plural = _('events')
        app_label = 'ellaschedule'

    def __unicode__(self):
        date_format = u'l, %s' % ugettext("DATE_FORMAT")
        return ugettext('%(title)s: %(start)s-%(end)s') % {
            'title': self.title,
            'start': date(self.start, date_format),
            'end': date(self.end, date_format),
        }

    def get_absolute_url(self):
        return reverse('event', args=[self.id])

    def create_relation(self, obj, distinction = None):
        """
        Creates a EventRelation between self and obj.
        """
        EventRelation.objects.create_relation(self, obj, distinction)

    def get_occurrences(self, start, end):
        """
        >>> rule = Rule(frequency = "MONTHLY", name = "Monthly")
        >>> rule.save()
        >>> event = Event(rule=rule, start=datetime.datetime(2008,1,1), end=datetime.datetime(2008,1,2))
        >>> event.rule
        <Rule: Monthly>
        >>> occurrences = event.get_occurrences(datetime.datetime(2008,1,24), datetime.datetime(2008,3,2))
        >>> ["%s to %s" %(o.start, o.end) for o in occurrences]
        ['2008-02-01 00:00:00 to 2008-02-02 00:00:00', '2008-03-01 00:00:00 to 2008-03-02 00:00:00']

        Ensure that if an event has no rule, that it appears only once.

        >>> event = Event(start=datetime.datetime(2008,1,1,8,0), end=datetime.datetime(2008,1,1,9,0))
        >>> occurrences = event.get_occurrences(datetime.datetime(2008,1,24), datetime.datetime(2008,3,2))
        >>> ["%s to %s" %(o.start, o.end) for o in occurrences]
        []

        """
        persisted_occurrences = self.occurrence_set.all()
        occ_replacer = OccurrenceReplacer(persisted_occurrences)
        occurrences = self._get_occurrence_list(start, end)
        final_occurrences = []
        for occ in occurrences:
            # replace occurrences with their persisted counterparts
            if occ_replacer.has_occurrence(occ):
                p_occ = occ_replacer.get_occurrence(
                        occ)
                # ...but only if they are within this period
                if p_occ.start < end and p_occ.end >= start:
                    final_occurrences.append(p_occ)
            else:
              final_occurrences.append(occ)
        # then add persisted occurrences which originated outside of this period but now
        # fall within it
        final_occurrences += occ_replacer.get_additional_occurrences(start, end)
        return final_occurrences

    def get_rrule_object(self):
        if self.rule is not None:
            params = self.rule.get_params()
            frequency = 'rrule.%s' % self.rule.frequency
            return rrule.rrule(eval(frequency), dtstart=self.start, **params)

    def _create_occurrence(self, start, end=None):
        if end is None:
            end = start + (self.end - self.start)
        return Occurrence(event=self,start=start,end=end, original_start=start, original_end=end)

    def get_occurrence(self, date):
        rule = self.get_rrule_object()
        if rule:
            next_occurrence = rule.after(date, inc=True)
        else:
            next_occurrence = self.start
        if next_occurrence == date:
            try:
                return Occurrence.objects.get(event = self, original_start = date)
            except Occurrence.DoesNotExist:
                return self._create_occurrence(next_occurrence)


    def _get_occurrence_list(self, start, end):
        """
        returns a list of occurrences for this event from start to end.
        """
        difference = (self.end - self.start)
        if self.rule is not None:
            occurrences = []
            if self.end_recurring_period and self.end_recurring_period < end:
                end = self.end_recurring_period
            rule = self.get_rrule_object()
            o_starts = rule.between(start-difference, end, inc=True)
            for o_start in o_starts:
                o_end = o_start + difference
                occurrences.append(self._create_occurrence(o_start, o_end))
            return occurrences
        else:
            # check if event is in the period
            if self.start < end and self.end >= start:
                return [self._create_occurrence(self.start)]
            else:
                return []

    def _occurrences_after_generator(self, after=None):
        """
        returns a generator that produces unpresisted occurrences after the
        datetime ``after``.
        """

        if after is None:
            after = datetime.datetime.now()
        rule = self.get_rrule_object()
        if rule is None:
            if self.end > after:
                yield self._create_occurrence(self.start, self.end)
            raise StopIteration
        date_iter = iter(rule)
        difference = self.end - self.start
        while True:
            o_start = date_iter.next()
            if o_start > self.end_recurring_period:
                raise StopIteration
            o_end = o_start + difference
            if o_end > after:
                yield self._create_occurrence(o_start, o_end)


    def occurrences_after(self, after=None):
        """
        returns a generator that produces occurrences after the datetime
        ``after``.  Includes all of the persisted Occurrences.
        """
        occ_replacer = OccurrenceReplacer(self.occurrence_set.all())
        generator = self._occurrences_after_generator(after)
        while True:
            next = generator.next()
            yield occ_replacer.get_occurrence(next)

    def get_user_authors(self):
        return [
            author.user for author in self.authors.all() if author.user
        ]

    user_authors = property(fget = get_user_authors)

    def get_agenda(self):
        """
        Return agenda for given event.
        Agenda = events that are inside given event (resp. it's occurence) and has
        given event as parent.
        """
        return Event.objects.filter(
            parent_event = self
        )

    def get_structured_agenda(self):
        """
        Return agenda in structured form, suitable for template printing:
        [
            {
            'date' : day_date,
            'places' : ['room A', 'room B'],
            'agenda' : {
                time : [event, event]
            }
        ]
        """
        events = self.get_agenda()

        days = set([event.start.date() for event in events])

        agenda = []

        #TODO: ugly spaghetti with ugly O(). Refactor, we have better sorts.
        for day in days:
            day_agenda = {
                'date' : day
            }
            times = {}
            start_times = set()
            places = set()
            for event in events:
                if event.start.date() == day:
                    places.add(event.place)
                    if not event.start in times:
                        times[event.start.time()] = []
                    times[event.start.time()].append(event)
                    start_times.add(event.start.time())

            places = list(places)
            start_times = list(start_times)
            start_times.sort()

            day_agenda['places'] = places
            day_agenda['agenda'] = {}

            for time in start_times:
                day_agenda['agenda'][time] = []
                for place in places:
                    add = None
                    for event in events:
                        if event.start.date() == day and event.start.time() == time and event.place == place:
                            add = event
                    day_agenda['agenda'][time].append(add)
            agenda.append(day_agenda)
        return agenda

class EventRelationManager(models.Manager):
    '''
    >>> EventRelation.objects.all().delete()
    >>> CalendarRelation.objects.all().delete()
    >>> data = {
    ...         'title': 'Test1',
    ...         'start': datetime.datetime(2008, 1, 1),
    ...         'end': datetime.datetime(2008, 1, 11)
    ...        }
    >>> Event.objects.all().delete()
    >>> event1 = Event(**data)
    >>> event1.save()
    >>> data['title'] = 'Test2'
    >>> event2 = Event(**data)
    >>> event2.save()
    >>> user1 = User(username='alice')
    >>> user1.save()
    >>> user2 = User(username='bob')
    >>> user2.save()
    >>> event1.create_relation(user1, 'owner')
    >>> event1.create_relation(user2, 'viewer')
    >>> event2.create_relation(user1, 'viewer')
    '''
    # Currently not supported
    # Multiple level reverse lookups of generic relations appears to be
    # unsupported in Django, which makes sense.
    #
    # def get_objects_for_event(self, event, model, distinction=None):
    #     '''
    #     returns a queryset full of instances of model, if it has an EventRelation
    #     with event, and distinction
    #     >>> event = Event.objects.get(title='Test1')
    #     >>> EventRelation.objects.get_objects_for_event(event, User, 'owner')
    #     [<User: alice>]
    #     >>> EventRelation.objects.get_objects_for_event(event, User)
    #     [<User: alice>, <User: bob>]
    #     '''
    #     if distinction:
    #         dist_q = Q(eventrelation__distinction = distinction)
    #     else:
    #         dist_q = Q()
    #     ct = ContentType.objects.get_for_model(model)
    #     return model.objects.filter(
    #         dist_q,
    #         eventrelation__content_type = ct,
    #         eventrelation__event = event
    #     )

    def get_events_for_object(self, content_object, distinction=None, inherit=True):
        '''
        returns a queryset full of events, that relate to the object through, the
        distinction

        If inherit is false it will not consider the calendars that the events
        belong to. If inherit is true it will inherit all of the relations and
        distinctions that any calendar that it belongs to has, as long as the
        relation has inheritable set to True.  (See Calendar)

        >>> event = Event.objects.get(title='Test1')
        >>> user = User.objects.get(username = 'alice')
        >>> EventRelation.objects.get_events_for_object(user, 'owner', inherit=False)
        [<Event: Test1: Tuesday, Jan. 1, 2008-Friday, Jan. 11, 2008>]

        If a distinction is not declared it will not vet the relations based on
        distinction.
        >>> EventRelation.objects.get_events_for_object(user, inherit=False)
        [<Event: Test1: Tuesday, Jan. 1, 2008-Friday, Jan. 11, 2008>, <Event: Test2: Tuesday, Jan. 1, 2008-Friday, Jan. 11, 2008>]

        Now if there is a Calendar
        >>> calendar = Calendar(name = 'MyProject')
        >>> calendar.save()

        And an event that belongs to that calendar
        >>> event = Event.objects.get(title='Test2')
        >>> calendar.events.add(event)

        If we relate this calendar to some object with inheritable set to true,
        that relation will be inherited
        >>> user = User.objects.get(username='bob')
        >>> cr = calendar.create_relation(user, 'viewer', True)
        >>> EventRelation.objects.get_events_for_object(user, 'viewer')
        [<Event: Test1: Tuesday, Jan. 1, 2008-Friday, Jan. 11, 2008>, <Event: Test2: Tuesday, Jan. 1, 2008-Friday, Jan. 11, 2008>]
        '''
        ct = ContentType.objects.get_for_model(type(content_object))
        if distinction:
            dist_q = Q(eventrelation__distinction = distinction)
            cal_dist_q = Q(calendar__calendarrelation__distinction = distinction)
        else:
            dist_q = Q()
            cal_dist_q = Q()
        if inherit:
            inherit_q = Q(
                cal_dist_q,
                calendar__calendarrelation__object_id = content_object.id,
                calendar__calendarrelation__content_type = ct,
                calendar__calendarrelation__inheritable = True,
            )
        else:
            inherit_q = Q()
        event_q = Q(dist_q, Q(eventrelation__object_id=content_object.id),Q(eventrelation__content_type=ct))
        return Event.objects.filter(inherit_q|event_q)

    def change_distinction(self, distinction, new_distinction):
        '''
        This function is for change the a group of eventrelations from an old
        distinction to a new one. It should only be used for managerial stuff.
        It is also expensive so it should be used sparingly.
        '''
        for relation in self.filter(distinction = distinction):
            relation.distinction = new_distinction
            relation.save()

    def create_relation(self, event, content_object, distinction=None):
        """
        Creates a relation between event and content_object.
        See EventRelation for help on distinction.
        """
        ct = ContentType.objects.get_for_model(type(content_object))
        object_id = content_object.id
        er = EventRelation(
            content_type = ct,
            object_id = object_id,
            event = event,
            distinction = distinction,
            content_object = content_object
        )
        er.save()
        return er


class EventRelation(models.Model):
    '''
    This is for relating data to an Event, there is also a distinction, so that
    data can be related in different ways.  A good example would be, if you have
    events that are only visible by certain users, you could create a relation
    between events and users, with the distinction of 'visibility', or
    'ownership'.

    event: a foreign key relation to an Event model.
    content_type: a foreign key relation to ContentType of the generic object
    object_id: the id of the generic object
    content_object: the generic foreign key to the generic object
    distinction: a string representing a distinction of the relation, User could
    have a 'veiwer' relation and an 'owner' relation for example.

    DISCLAIMER: while this model is a nice out of the box feature to have, it
    may not scale well.  If you use this keep that in mindself.
    '''
    event = models.ForeignKey(Event, verbose_name=_("event"))
    content_type = models.ForeignKey(ContentType)
    object_id = models.IntegerField()
    content_object = generic.GenericForeignKey('content_type', 'object_id')
    distinction = models.CharField(_("distinction"), max_length = 20, null=True)

    objects = EventRelationManager()

    class Meta:
        verbose_name = _("event relation")
        verbose_name_plural = _("event relations")
        app_label = 'ellaschedule'

    def __unicode__(self):
        return u'%s(%s)-%s' % (self.event.title, self.distinction, self.content_object)




class Occurrence(Publishable):
    event = models.ForeignKey(Event, verbose_name=_("event"))
    start = models.DateTimeField(_("start"))
    end = models.DateTimeField(_("end"))
    cancelled = models.BooleanField(_("cancelled"), default=False)
    original_start = models.DateTimeField(_("original start"))
    original_end = models.DateTimeField(_("original end"))

    class Meta:
        verbose_name = _("occurrence")
        verbose_name_plural = _("occurrences")
        app_label = 'ellaschedule'

    def __init__(self, *args, **kwargs):
        super(Occurrence, self).__init__(*args, **kwargs)
        if self.title is None:
            self.title = self.event.title
        if self.description is None:
            self.description = self.event.description


    def moved(self):
        return self.original_start != self.start or self.original_end != self.end
    moved = property(moved)

    def move(self, new_start, new_end):
        self.start = new_start
        self.end = new_end
        self.save()

    def cancel(self):
        self.cancelled = True
        self.save()

    def uncancel(self):
        self.cancelled = False
        self.save()

    def get_absolute_url(self):
        if self.pk is not None:
            return reverse('occurrence', kwargs={'occurrence_id': self.pk,
                'event_id': self.event.id})
        return reverse('occurrence_by_date', kwargs={
            'event_id': self.event.id,
            'year': self.start.year,
            'month': self.start.month,
            'day': self.start.day,
            'hour': self.start.hour,
            'minute': self.start.minute,
            'second': self.start.second,
        })

    def get_cancel_url(self):
        if self.pk is not None:
            return reverse('cancel_occurrence', kwargs={'occurrence_id': self.pk,
                'event_id': self.event.id})
        return reverse('cancel_occurrence_by_date', kwargs={
            'event_id': self.event.id,
            'year': self.start.year,
            'month': self.start.month,
            'day': self.start.day,
            'hour': self.start.hour,
            'minute': self.start.minute,
            'second': self.start.second,
        })

    def get_edit_url(self):
        if self.pk is not None:
            return reverse('edit_occurrence', kwargs={'occurrence_id': self.pk,
                'event_id': self.event.id})
        return reverse('edit_occurrence_by_date', kwargs={
            'event_id': self.event.id,
            'year': self.start.year,
            'month': self.start.month,
            'day': self.start.day,
            'hour': self.start.hour,
            'minute': self.start.minute,
            'second': self.start.second,
        })

    def __unicode__(self):
        return ugettext("%(start)s to %(end)s") % {
            'start': self.start,
            'end': self.end,
        }

    def __cmp__(self, other):
        rank = cmp(self.start, other.start)
        if rank == 0:
            return cmp(self.end, other.end)
        return rank

    def __eq__(self, other):
        return self.event == other.event and self.original_start == other.original_start and self.original_end == other.original_end
