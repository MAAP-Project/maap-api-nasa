# This file is part of the MapProxy project.
# Copyright (C) 2010 Omniscale <http://omniscale.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from mapproxy.config.config import (
    base_config, abspath, load_base_config, load_default_config,
    finish_base_config, Options, local_base_config,
)

__all__ = ['base_config', 'abspath', 'load_base_config', 'load_default_config',
           'finish_base_config', 'Options', 'local_base_config']