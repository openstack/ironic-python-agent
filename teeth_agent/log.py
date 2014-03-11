"""
Copyright 2013 Rackspace, Inc.

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import string

import structlog

import traceback

EXCEPTION_LOG_METHODS = ['error']


def _capture_stack_trace(logger, method, event):
    if method in EXCEPTION_LOG_METHODS:
        event['exception'] = traceback.format_exc()

    return event


def _format_event(logger, method, event):
    """Formats the log message using keyword args.
    log('hello {keyword}', keyword='world') should log: "hello world"
    Removes the keywords used for formatting from the logged message.
    Throws a KeyError if the log message requires formatting but doesn't
    have enough keys to format.
    """
    if 'event' not in event:
        # nothing to format, e.g. _log_request in teeth_rest/component
        return event
    # Get a list of fields that need to be filled.
    formatter = string.Formatter()
    try:
        formatted = formatter.format(event['event'], **event)
    except KeyError:
        keys = formatter.parse(event['event'])
        # index 1 is the key name
        keys = [item[1] for item in keys]
        missing_keys = list(set(keys) - set(event))
        raise KeyError("Log formatter missing keys: {}, cannot format."
                       .format(missing_keys))
    event['event'] = formatted
    return event


def configure(pretty=False):
    processors = [
        _capture_stack_trace,
        _format_event,
    ]

    if pretty:
        processors.append(structlog.processors.ExceptionPrettyPrinter())
        processors.append(structlog.processors.KeyValueRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors
    )
