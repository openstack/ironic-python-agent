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

from teeth_agent.base_task import BaseTask
import treq


class ImageDownloaderTask(BaseTask):
    """Download image to cache. """
    task_name = 'image_download'

    def __init__(self, client, task_id, image_info, destination_filename, reporting_interval=10):
        super(ImageDownloaderTask, self).__init__(client, task_id, reporting_interval=reporting_interval)
        self._destination_filename = destination_filename
        self._image_id = image_info.id
        self._image_hashes = image_info.hashes
        self._iamge_urls = image_info.urls
        self._destination_filename = destination_filename

    def _run(self):
        # TODO: pick by protocol priority.
        url = self._iamge_urls[0]
        # TODO: more than just download, sha1 it.
        return self._download_image_to_file(url)

    def _tick(self):
        # TODO: get file download percentages.
        self.percent = 0
        super(ImageDownloaderTask, self)._tick()

    def _download_image_to_file(self, url):
        destination = open(self._destination_filename, 'wb')

        def push(data):
            if self.running:
                destination.write(data)

        d = treq.get(url)
        d.addCallback(treq.collect, push)
        d.addBoth(lambda _: destination.close())
        return d
