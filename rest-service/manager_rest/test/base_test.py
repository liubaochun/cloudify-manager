#########
# Copyright (c) 2013 GigaSpaces Technologies Ltd. All rights reserved
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
#  * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  * See the License for the specific language governing permissions and
#  * limitations under the License.

import unittest
import json
import urllib
import urllib2
import tempfile
import time
import os

from manager_rest import utils, config, storage_manager, archiving
from manager_rest.file_server import FileServer
from cloudify_rest_client import CloudifyClient
from cloudify_rest_client.client import HTTPClient


STORAGE_MANAGER_MODULE_NAME = 'file_storage_manager'
FILE_SERVER_PORT = 53229
FILE_SERVER_BLUEPRINTS_FOLDER = 'blueprints'
FILE_SERVER_UPLOADED_BLUEPRINTS_FOLDER = 'uploaded-blueprints'
FILE_SERVER_RESOURCES_URI = '/resources'


def build_query_string(query_params):
    query_string = ''
    if query_params and len(query_params) > 0:
        query_string += urllib.urlencode(query_params) + '&'
    return query_string


class MockHTTPClient(HTTPClient):

    def __init__(self, app, user=None, password=None):
        super(MockHTTPClient, self).__init__(host='localhost',
                                             user=user,
                                             password=password)
        self.app = app

    def _do_request(self, requests_method, uri, data, params, headers,
                    expected_status_code):
        if 'get' in requests_method.__name__:
            response = self.app.get(uri,
                                    headers=headers,
                                    query_string=build_query_string(params))

        elif 'put' in requests_method.__name__:
            response = self.app.put(uri,
                                    headers=headers,
                                    data=data,
                                    query_string=build_query_string(params))
        elif 'post' in requests_method.__name__:
            response = self.app.post(uri,
                                     headers=headers,
                                     data=data,
                                     query_string=build_query_string(params))
        elif 'patch' in requests_method.__name__:
            response = self.app.patch(uri,
                                      headers=headers,
                                      data=data,
                                      query_string=build_query_string(params))
        else:
            raise NotImplemented()

        if response.status_code != expected_status_code:
            response.content = response.data
            response.json = lambda: json.loads(response.data)
            self._raise_client_error(response, uri)

        return json.loads(response.data)


class BaseServerTestCase(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        super(BaseServerTestCase, self).__init__(*args, **kwargs)
        self._secured = False

    def create_client(self, user=None, password=None):
        client = CloudifyClient('localhost',
                                user=user,
                                password=password)
        mock_http_client = MockHTTPClient(self.app,
                                          user=user,
                                          password=password)
        client._client = mock_http_client
        client.blueprints.api = mock_http_client
        client.deployments.api = mock_http_client
        client.deployments.outputs.api = mock_http_client
        client.deployment_modifications.api = mock_http_client
        client.executions.api = mock_http_client
        client.nodes.api = mock_http_client
        client.node_instances.api = mock_http_client
        client.manager.api = mock_http_client
        client.evaluate.api = mock_http_client

        return client

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rest_service_log = tempfile.mkstemp()[1]
        self.file_server = FileServer(self.tmpdir)
        self.file_server.start()
        storage_manager.storage_manager_module_name = \
            STORAGE_MANAGER_MODULE_NAME

        # workaround for setting the rest service log path, since it's
        # needed when 'server' module is imported.
        # right after the import the log path is set normally like the rest
        # of the variables (used in the reset_state)
        tmp_conf_file = tempfile.mkstemp()[1]
        json.dump({'rest_service_log_path': self.rest_service_log},
                  open(tmp_conf_file, 'w'))
        os.environ['MANAGER_REST_CONFIG_PATH'] = tmp_conf_file
        try:
            from manager_rest import server
        finally:
            del(os.environ['MANAGER_REST_CONFIG_PATH'])

        server.reset_state(self.create_configuration())
        utils.copy_resources(config.instance().file_server_root)
        server.setup_app()
        server.app.config['Testing'] = True
        self.app = server.app.test_client()
        self.client = self.create_client()

    def tearDown(self):
        self.file_server.stop()

    def create_configuration(self):
        from manager_rest.config import Config
        test_config = Config()
        test_config.test_mode = True
        test_config.file_server_root = self.tmpdir
        test_config.file_server_base_uri = 'http://localhost:{0}'.format(
            FILE_SERVER_PORT)
        test_config.file_server_blueprints_folder = \
            FILE_SERVER_BLUEPRINTS_FOLDER
        test_config.file_server_uploaded_blueprints_folder = \
            FILE_SERVER_UPLOADED_BLUEPRINTS_FOLDER
        test_config.file_server_resources_uri = FILE_SERVER_RESOURCES_URI
        test_config.rest_service_log_path = self.rest_service_log

        # security config
        test_config.secured_server = self._secured
        if self._secured:
            test_config.securest_userstore_driver = {
                'implementation':
                    'flask_securest.userstores.file:FileUserstore',
                'properties': {
                    'userstore_file': 'users.yaml',
                    'identifying_attribute': 'username'
                }
            }
            test_config.securest_authentication_methods = [{
                'name': 'password',
                'implementation':
                    'flask_securest.authentication_providers.password'
                    ':PasswordAuthenticator',
                'properties': {
                    'password_hash': 'plaintext'
                }
            }]

        return test_config

    def post(self, resource_path, data, query_params=None):
        result = self.app.post(urllib.quote(resource_path),
                               content_type='application/json',
                               data=json.dumps(data),
                               query_string=build_query_string(query_params))
        result.json = json.loads(result.data)
        return result

    def post_file(self, resource_path, file_path, query_params=None):
        with open(file_path) as f:
            result = self.app.post(urllib.quote(resource_path),
                                   data=f.read(),
                                   query_string=build_query_string(
                                       query_params))
            result.json = json.loads(result.data)
            return result

    def put_file(self, resource_path, file_path, query_params=None):
        with open(file_path) as f:
            result = self.app.put(urllib.quote(resource_path),
                                  data=f.read(),
                                  query_string=build_query_string(
                                      query_params))
            result.json = json.loads(result.data)
            return result

    def put(self, resource_path, data=None, query_params=None):
        result = self.app.put(urllib.quote(resource_path),
                              content_type='application/json',
                              data=json.dumps(data) if data else None,
                              query_string=build_query_string(query_params))
        result.json = json.loads(result.data)
        return result

    def patch(self, resource_path, data):
        result = self.app.patch(urllib.quote(resource_path),
                                content_type='application/json',
                                data=json.dumps(data))
        result.json = json.loads(result.data)
        return result

    def get(self, resource_path, query_params=None, headers=None):
        result = self.app.get(urllib.quote(resource_path),
                              headers=headers,
                              query_string=build_query_string(query_params))
        result.json = json.loads(result.data)
        return result

    def head(self, resource_path):
        result = self.app.head(urllib.quote(resource_path))
        return result

    def delete(self, resource_path, query_params=None):
        result = self.app.delete(urllib.quote(resource_path),
                                 query_string=build_query_string(query_params))
        result.json = json.loads(result.data)
        return result

    def check_if_resource_on_fileserver(self, blueprint_id, resource_path):
        url = 'http://localhost:{0}/{1}/{2}/{3}'.format(
            FILE_SERVER_PORT, FILE_SERVER_BLUEPRINTS_FOLDER,
            blueprint_id, resource_path)
        try:
            urllib2.urlopen(url)
            return True
        except urllib2.HTTPError:
            return False

    def archive_mock_blueprint(self, archive_func=archiving.make_targzfile,
                               blueprint_dir='mock_blueprint'):
        archive_path = tempfile.mkstemp()[1]
        source_dir = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), blueprint_dir)
        archive_func(archive_path, source_dir)
        return archive_path

    def put_blueprint_args(self, blueprint_file_name=None,
                           blueprint_id='blueprint',
                           archive_func=archiving.make_targzfile,
                           blueprint_dir='mock_blueprint'):

        resource_path = '/blueprints/{0}'.format(blueprint_id)
        result = [
            resource_path,
            self.archive_mock_blueprint(archive_func, blueprint_dir),
        ]

        if blueprint_file_name:
            data = {'application_file_name': blueprint_file_name}
        else:
            data = {}

        result.append(data)
        return result

    def put_deployment(self,
                       deployment_id='deployment',
                       blueprint_file_name=None,
                       blueprint_id='blueprint',
                       inputs=None):
        blueprint_response = self.put_file(
            *self.put_blueprint_args(blueprint_file_name, blueprint_id)).json

        if 'error_code' in blueprint_response:
            raise RuntimeError(
                '{}: {}'.format(blueprint_response['error_code'],
                                blueprint_response['message']))

        blueprint_id = blueprint_response['id']
        deployment = self.client.deployments.create(blueprint_id,
                                                    deployment_id,
                                                    inputs=inputs)
        return blueprint_id, deployment.id, blueprint_response, deployment

    def wait_for_url(self, url, timeout=5):
        end = time.time() + timeout

        while end >= time.time():
            try:
                status = urllib.urlopen(url).getcode()
                if status == 200:
                    return
            except IOError:
                time.sleep(1)

        raise RuntimeError('Url {0} is not available (waited {1} '
                           'seconds)'.format(url, timeout))
