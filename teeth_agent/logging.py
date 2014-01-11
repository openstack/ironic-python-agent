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

import traceback

import structlog

EXCEPTION_LOG_METHODS = ['error']


def _capture_stack_trace(logger, method, event):
    if method in EXCEPTION_LOG_METHODS:
        event['exception'] = traceback.format_exc()

    return event


def configure(pretty=False):
    processors = [
        _capture_stack_trace,
    ]

    if pretty:
        processors.append(structlog.processors.ExceptionPrettyPrinter())
        processors.append(structlog.processors.KeyValueRenderer())
    else:
        processors.append(structlog.processors.JSONRenderer())

    structlog.configure(
        processors=processors
    )
