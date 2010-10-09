from django.conf import settings
from django.db.models.signals import pre_save

from ella.core.models import Category

from django.contrib.sites.models import Site
from django.template.defaultfilters import slugify

from models import Event, Calendar


def get_default_category():
    try:
        return Category.objects.get(
            site = Site.objects.get_current(),
            tree_parent = None
        )
    except Category.DoesNotExist:
        title = u"Default category"
        
        return Category.objects.create(
            site = Site.objects.get_current(),
            tree_path = "",
            tree_parent = None,
            title = title,
            slug = slugify(title)
        )


def optionnal_calendar(sender, **kwargs):
    event = kwargs.pop('instance')

    if not isinstance(event, Event):
        return True
    try:
        if not event.calendar:
            calendar = Calendar._default_manager.get(name='default')
    except Calendar.DoesNotExist:
        name = getattr(settings, "EVENT_DEFAULT_CALENDAR_NAME", None) or u"default"
        calendar = Calendar(
            name = name,
            slug = slugify(name),
            category = get_default_category()
        )
        calendar.save()
        event.calendar = calendar
        
    return True

pre_save.connect(optionnal_calendar)
