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

import argparse

from teeth_agent import decom
from teeth_agent import logging


def run():
    parser = argparse.ArgumentParser(
        description='Run the teeth-agent in decom mode')

    parser.add_argument('--api-url',
                        required=True,
                        help='URL of the Teeth agent API')

    args = parser.parse_args()

    logging.configure()
    decom.DecomAgent('0.0.0.0', 9999, args.api_url).run()
