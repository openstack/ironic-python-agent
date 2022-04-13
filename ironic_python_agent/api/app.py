# Copyright 2013 Rackspace, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import json

from ironic_lib import metrics_utils
from oslo_log import log
from oslo_service import wsgi
import werkzeug
from werkzeug import exceptions as http_exc
from werkzeug import routing

from ironic_python_agent import encoding


LOG = log.getLogger(__name__)
_CUSTOM_MEDIA_TYPE = 'application/vnd.openstack.ironic-python-agent.v1+json'
_DOCS_URL = 'https://docs.openstack.org/ironic-python-agent'


class Request(werkzeug.Request):
    """Custom request class with JSON support."""


def jsonify(value, status=200):
    """Convert value to a JSON response using the custom encoder."""
    encoder = encoding.RESTJSONEncoder()
    data = encoder.encode(value)
    return werkzeug.Response(data, status=status, mimetype='application/json')


def make_link(url, rel_name, resource='', resource_args='',
              bookmark=False, type_=None):
    if rel_name == 'describedby':
        url = _DOCS_URL
        type_ = 'text/html'
    elif rel_name == 'bookmark':
        bookmark = True

    template = ('%(root)s/%(resource)s' if bookmark
                else '%(root)s/v1/%(resource)s')
    template += ('%(args)s'
                 if resource_args.startswith('?') or not resource_args
                 else '/%(args)s')

    result = {'href': template % {'root': url,
                                  'resource': resource,
                                  'args': resource_args},
              'rel': rel_name}
    if type_:
        result['type'] = type_
    return result


def version(url):
    return {
        'id': 'v1',
        'links': [
            make_link(url, 'self', 'v1', bookmark=True),
            make_link(url, 'describedby', bookmark=True),
        ],
    }


# Emulate WSME format
def format_exception(value):
    code = getattr(value, 'status_code', None) or getattr(value, 'code', 500)
    return {
        'faultcode': 'Server' if code >= 500 else 'Client',
        'faultstring': str(value),
    }


class Application(object):

    def __init__(self, agent, conf):
        """Set up the API app.

        :param agent: an :class:`ironic_python_agent.agent.IronicPythonAgent`
                      instance.
        :param conf: configuration object.
        """
        self.agent = agent
        self.service = None
        self._conf = conf
        self.url_map = routing.Map([
            routing.Rule('/', endpoint='root', methods=['GET']),
            routing.Rule('/v1/', endpoint='v1', methods=['GET']),
            routing.Rule('/v1/status', endpoint='status', methods=['GET']),
            routing.Rule('/v1/commands/', endpoint='list_commands',
                         methods=['GET']),
            routing.Rule('/v1/commands/<cmd>', endpoint='get_command',
                         methods=['GET']),
            routing.Rule('/v1/commands/', endpoint='run_command',
                         methods=['POST']),
            # Use the default version (i.e. v1) when the version is missing
            routing.Rule('/status', endpoint='status', methods=['GET']),
            routing.Rule('/commands/', endpoint='list_commands',
                         methods=['GET']),
            routing.Rule('/commands/<cmd>', endpoint='get_command',
                         methods=['GET']),
            routing.Rule('/commands/', endpoint='run_command',
                         methods=['POST']),
        ])

    def __call__(self, environ, start_response):
        """WSGI entry point."""
        try:
            request = Request(environ)
            adapter = self.url_map.bind_to_environ(request.environ)
            endpoint, values = adapter.match()
            response = getattr(self, "api_" + endpoint)(request, **values)
        except Exception as exc:
            response = self.handle_exception(environ, exc)
        return response(environ, start_response)

    def start(self, tls_cert_file=None, tls_key_file=None):
        """Start the API service in the background."""
        if tls_cert_file and tls_key_file:
            self._conf.set_override('cert_file', tls_cert_file, group='ssl')
            self._conf.set_override('key_file', tls_key_file, group='ssl')
            use_tls = True
        else:
            use_tls = self._conf.listen_tls

        self.service = wsgi.Server(self._conf, 'ironic-python-agent', app=self,
                                   host=self.agent.listen_address.hostname,
                                   port=self.agent.listen_address.port,
                                   use_ssl=use_tls)
        self.service.start()
        LOG.info('Started API service on port %s',
                 self.agent.listen_address.port)

    def stop(self):
        """Stop the API service."""
        LOG.debug("Stopping the API service.")
        if self.service is None:
            return
        self.service.stop()
        self.service = None
        LOG.info('Stopped API service on port %s',
                 self.agent.listen_address.port)

    def handle_exception(self, environ, exc):
        """Handle an exception during request processing."""
        if isinstance(exc, http_exc.HTTPException):
            if exc.code and exc.code < 400:
                return exc  # redirect
            resp = exc.get_response(environ)
            resp.data = json.dumps(format_exception(exc))
            resp.content_type = 'application/json'
            return resp
        else:
            formatted = format_exception(exc)
            if formatted['faultcode'] == 'Server':
                LOG.exception('Internal server error: %s', exc)
            return jsonify(formatted, status=getattr(exc, 'status_code', 500))

    def api_root(self, request):
        url = request.url_root.rstrip('/')
        return jsonify({
            'name': 'OpenStack Ironic Python Agent API',
            'description': ('Ironic Python Agent is a provisioning agent for '
                            'OpenStack Ironic'),
            'versions': [version(url)],
            'default_version': version(url),
        })

    def api_v1(self, request):
        url = request.url_root.rstrip('/')
        return jsonify(dict({
            'commands': [
                make_link(url, 'self', 'commands'),
                make_link(url, 'bookmark', 'commands'),
            ],
            'status': [
                make_link(url, 'self', 'status'),
                make_link(url, 'bookmark', 'status'),
            ],
            'media_types': [
                {'base': 'application/json',
                 'type': _CUSTOM_MEDIA_TYPE},
            ],
        }, **version(url)))

    def api_status(self, request):
        with metrics_utils.get_metrics_logger(__name__).timer('get_status'):
            status = self.agent.get_status()
            return jsonify(status)

    def api_list_commands(self, request):
        with metrics_utils.get_metrics_logger(__name__).timer('list_commands'):
            results = self.agent.list_command_results()
            return jsonify({'commands': results})

    def api_get_command(self, request, cmd):
        with metrics_utils.get_metrics_logger(__name__).timer('get_command'):
            result = self.agent.get_command_result(cmd)
            wait = request.args.get('wait')

            if wait and wait.lower() == 'true':
                result.join()

            return jsonify(result)

    def api_run_command(self, request):
        body = request.get_json(force=True)
        if ('name' not in body or 'params' not in body
                or not isinstance(body['params'], dict)):
            raise http_exc.BadRequest('Missing or invalid name or params')

        token = request.args.get('agent_token', None)
        if not self.agent.validate_agent_token(token):
            raise http_exc.Unauthorized(
                'Token invalid.')
        with metrics_utils.get_metrics_logger(__name__).timer('run_command'):
            result = self.agent.execute_command(body['name'], **body['params'])
            wait = request.args.get('wait')
            if wait and wait.lower() == 'true':
                result.join()
            return jsonify(result)
