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

import os

from teeth_agent.base_task import MultiTask, BaseTask
from teeth_agent.cache_image import ImageDownloaderTask


__all__ = ['CacheImagesTask', 'PrepareImageTask']


class CacheImagesTask(MultiTask):

    """Cache an array of images on a machine."""

    task_name = 'cache_images'

    def __init__(self, client, task_id, images, reporting_interval=10):
        super(CacheImagesTask, self).__init__(client, task_id, reporting_interval=reporting_interval)
        self._images = images
        for image in self._images:
            image_path = os.path.join(client.get_cache_path(), image.id + '.img')
            t = ImageDownloaderTask(client,
                                    task_id, image,
                                    image_path,
                                    reporting_interval=reporting_interval)
            self.add_task(t)


class PrepareImageTask(BaseTask):

    """Prepare an image to be ran on the machine."""

    task_name = 'prepare_image'

    def __init__(self, client, task_id, image_info, reporting_interval=10):
        super(PrepareImageTask, self).__init__(client, task_id)
        self._image_info = image_info

    def _run(self):
        """Run the Prepare Image task."""
        self.log.msg('running prepare_image', image_info=self._image_info)
        pass
