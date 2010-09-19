#!/usr/bin/env python
# -*- coding: utf-8 -*-
from setuptools import setup, find_packages
 
setup(
    name='ellaschedule',
    version='0.1',
    description='A calendaring app for Ella CMS, based on django-schedule.',
    author='Almad',
    author_email='bugs@almad.net',
    url='http://github.com/rpgplanet/django-ella-schedule/tree/master',
    packages=[
        'ellaschedule',
        'ellaschedule.feeds',
        'ellaschedule.management',
        'ellaschedule.management.commands',
        'ellaschedule.models',
        'ellaschedule.templatetags',
        'ellaschedule.tests',
    ],
    include_package_data=True,
    zip_safe=False,
    classifiers=['Development Status :: 3 - Alpha',
                 'Environment :: Web Environment',
                 'Framework :: Django',
                 'Intended Audience :: Developers',
                 'License :: OSI Approved :: BSD License',
                 'Operating System :: OS Independent',
                 'Programming Language :: Python',
                 'Topic :: Utilities'],
    install_requires=['setuptools', 'vobject', 'python-dateutil'],
    license='BSD',
    test_suite = "schedule.tests",
)
