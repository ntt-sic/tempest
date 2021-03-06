# Copyright 2014 Mirantis.inc
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

import time
import urllib

from tempest.api.network import common as net_common
from tempest.common import ssh
from tempest.common.utils import data_utils
from tempest import config
from tempest import exceptions
from tempest.scenario import manager
from tempest import test

config = config.CONF


class TestLoadBalancerBasic(manager.NetworkScenarioTest):

    """
    This test checks basic load balancing.

    The following is the scenario outline:
    1. Create an instance
    2. SSH to the instance and start two servers
    3. Create a load balancer with two members and with ROUND_ROBIN algorithm
       associate the VIP with a floating ip
    4. Send 10 requests to the floating ip and check that they are shared
       between the two servers and that both of them get equal portions
    of the requests
    """

    @classmethod
    def check_preconditions(cls):
        super(TestLoadBalancerBasic, cls).check_preconditions()
        cfg = config.network
        if not test.is_extension_enabled('lbaas', 'network'):
            msg = 'LBaaS Extension is not enabled'
            cls.enabled = False
            raise cls.skipException(msg)
        if not (cfg.tenant_networks_reachable or cfg.public_network_id):
            msg = ('Either tenant_networks_reachable must be "true", or '
                   'public_network_id must be defined.')
            cls.enabled = False
            raise cls.skipException(msg)

    @classmethod
    def setUpClass(cls):
        super(TestLoadBalancerBasic, cls).setUpClass()
        cls.check_preconditions()
        cls.security_groups = {}
        cls.servers_keypairs = {}
        cls.members = []
        cls.floating_ips = {}
        cls.port1 = 80
        cls.port2 = 88

    def _create_security_groups(self):
        self.security_groups[self.tenant_id] =\
            self._create_security_group_neutron(tenant_id=self.tenant_id)

    def _create_server(self):
        tenant_id = self.tenant_id
        name = data_utils.rand_name("smoke_server-")
        keypair = self.create_keypair(name='keypair-%s' % name)
        security_groups = [self.security_groups[tenant_id].name]
        net = self.list_networks(tenant_id=self.tenant_id)[0]
        self.network = net_common.DeletableNetwork(client=self.network_client,
                                                   **net['network'])
        create_kwargs = {
            'nics': [
                {'net-id': self.network.id},
            ],
            'key_name': keypair.name,
            'security_groups': security_groups,
        }
        server = self.create_server(name=name,
                                    create_kwargs=create_kwargs)
        self.servers_keypairs[server] = keypair
        self.assertTrue(self.servers_keypairs)

    def _start_servers(self):
        """
        1. SSH to the instance
        2. Start two servers listening on ports 80 and 88 respectively
        """
        for server in self.servers_keypairs.keys():
            ssh_login = config.compute.image_ssh_user
            private_key = self.servers_keypairs[server].private_key
            network_name = self.network.name

            ip_address = server.networks[network_name][0]
            ssh_client = ssh.Client(ip_address, ssh_login,
                                    pkey=private_key,
                                    timeout=100)
            start_server = "while true; do echo -e 'HTTP/1.0 200 OK\r\n\r\n" \
                           "%(server)s' | sudo nc -l -p %(port)s ; done &"
            cmd = start_server % {'server': 'server1',
                                  'port': self.port1}
            ssh_client.exec_command(cmd)
            cmd = start_server % {'server': 'server2',
                                  'port': self.port2}
            ssh_client.exec_command(cmd)

    def _check_connection(self, check_ip):
        def try_connect(ip):
            try:
                urllib.urlopen("http://{0}/".format(ip))
                return True
            except IOError:
                return False
        timeout = config.compute.ping_timeout
        timer = 0
        while not try_connect(check_ip):
            time.sleep(1)
            timer += 1
            if timer >= timeout:
                message = "Timed out trying to connect to %s" % check_ip
                raise exceptions.TimeoutException(message)

    def _create_pool(self):
        """Create a pool with ROUND_ROBIN algorithm."""
        # get tenant subnet and verify there's only one
        subnet = self._list_subnets(tenant_id=self.tenant_id)[0]
        self.subnet = net_common.DeletableSubnet(client=self.network_client,
                                                 **subnet['subnet'])
        self.pool = super(TestLoadBalancerBasic, self)._create_pool(
            'ROUND_ROBIN',
            'HTTP',
            self.subnet.id)
        self.assertTrue(self.pool)

    def _create_members(self, network_name, server_ids):
        """
        Create two members.

        In case there is only one server, create both members with the same ip
        but with different ports to listen on.
        """
        servers = self.compute_client.servers.list()
        for server in servers:
            if server.id in server_ids:
                ip = server.networks[network_name][0]
                pool_id = self.pool.id
                if len(set(server_ids)) == 1 or len(servers) == 1:
                    member1 = self._create_member(ip, self.port1, pool_id)
                    member2 = self._create_member(ip, self.port2, pool_id)
                    self.members.extend([member1, member2])
                else:
                    member = self._create_member(ip, self.port1, pool_id)
                    self.members.append(member)
        self.assertTrue(self.members)

    def _assign_floating_ip_to_vip(self, vip):
        public_network_id = config.network.public_network_id
        port_id = vip.port_id
        floating_ip = self._create_floating_ip(vip, public_network_id,
                                               port_id=port_id)
        self.floating_ips.setdefault(vip.id, [])
        self.floating_ips[vip.id].append(floating_ip)

    def _create_load_balancer(self):
        self._create_pool()
        self._create_members(self.network.name,
                             [self.servers_keypairs.keys()[0].id])
        subnet_id = self.subnet.id
        pool_id = self.pool.id
        self.vip = super(TestLoadBalancerBasic, self)._create_vip('HTTP', 80,
                                                                  subnet_id,
                                                                  pool_id)
        self._status_timeout(NeutronRetriever(self.network_client,
                                              self.network_client.vip_path,
                                              net_common.DeletableVip),
                             self.vip.id,
                             expected_status='ACTIVE')
        self._assign_floating_ip_to_vip(self.vip)

    def _check_load_balancing(self):
        """
        1. Send 10 requests on the floating ip associated with the VIP
        2. Check that the requests are shared between
           the two servers and that both of them get equal portions
           of the requests
        """

        vip = self.vip
        floating_ip_vip = self.floating_ips[vip.id][0]['floating_ip_address']
        self._check_connection(floating_ip_vip)
        resp = []
        for count in range(10):
            resp.append(
                urllib.urlopen(
                    "http://{0}/".format(floating_ip_vip)).read())
        self.assertEqual(set(["server1\n", "server2\n"]), set(resp))
        self.assertEqual(5, resp.count("server1\n"))
        self.assertEqual(5, resp.count("server2\n"))

    @test.skip_because(bug="1277381")
    @test.attr(type='smoke')
    @test.services('compute', 'network')
    def test_load_balancer_basic(self):
        self._create_security_groups()
        self._create_server()
        self._start_servers()
        self._create_load_balancer()
        self._check_load_balancing()


class NeutronRetriever(object):
    def __init__(self, network_client, path, resource):
        self.network_client = network_client
        self.path = path
        self.resource = resource

    def get(self, thing_id):
        obj = self.network_client.get(self.path % thing_id)
        return self.resource(client=self.network_client, **obj.values()[0])
