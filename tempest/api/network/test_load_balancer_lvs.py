# Copyright 2013 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

from tempest.api.network import base
from tempest.api.network import test_load_balancer
from tempest.common.utils import data_utils
from tempest import test
import time


class LoadBalancerTestJSON(test_load_balancer.LoadBalancerTestJSON):
    _interface = 'json'

    """
    Tests the following operations in the Neutron API using the REST client for
    Neutron:

        create vIP, and Pool
        show vIP
        list vIP
        update vIP
        delete vIP
        update pool
        delete pool
        show pool
        list pool
        health monitoring operations
    """

    @classmethod
    def setUpClass(cls):
        super(test_load_balancer.LoadBalancerTestJSON, cls).setUpClass()
        if not test.is_extension_enabled('lbaas', 'network'):
            msg = "lbaas extension not enabled."
            raise cls.skipException(msg)
        cls.network = cls.create_network()
        cls.name = cls.network['name']
        cls.subnet = cls.create_subnet(cls.network)
        pool_name = data_utils.rand_name('pool-')
        vip_name = data_utils.rand_name('vip-')
        router_name = data_utils.rand_name('router-')
        cls.router = cls.create_router(router_name, True,
                                       cls.network_cfg.public_network_id)
        cls.create_router_interface(cls.router['id'], cls.subnet['id'])
        time.sleep(5)
        cls.pool = cls.create_pool(pool_name, "ROUND_ROBIN",
                                   "HTTP", cls.subnet, 'lvs',
                                   router=cls.router)
        cls.vip = cls.create_vip(name=vip_name,
                                 protocol="HTTP",
                                 protocol_port=80,
                                 subnet=cls.subnet,
                                 pool=cls.pool)
        cls.member = cls.create_member(80, cls.pool)
        cls.health_monitor = cls.create_health_monitor(delay=4,
                                                       max_retries=3,
                                                       Type="TCP",
                                                       timeout=1)


class LoadBalancerTestXML(LoadBalancerTestJSON):
    _interface = 'xml'
