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


"""
Teeth Agent Twisted Application Plugin.
"""

from twisted.application.service import ServiceMaker

TeethAgent = ServiceMaker(
    "Teeth Agent Client Application",
    "teeth_agent.service",
    "Teeth Agent for decomissioning and standbye",
    "teeth-agent"
)