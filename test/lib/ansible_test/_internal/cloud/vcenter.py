"""VMware vCenter plugin for integration tests."""
from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

import os

from . import (
    CloudProvider,
    CloudEnvironment,
    CloudEnvironmentConfig,
)

from ..util import (
    display,
    ConfigParser,
    ApplicationError,
)

from ..containers import (
    run_support_container,
)


class VcenterProvider(CloudProvider):
    """VMware vcenter/esx plugin. Sets up cloud resources for tests."""
    DOCKER_SIMULATOR_NAME = 'vcenter-simulator'

    def __init__(self, args):
        """
        :type args: TestConfig
        """
        super(VcenterProvider, self).__init__(args)

        # The simulator must be pinned to a specific version to guarantee CI passes with the version used.
        if os.environ.get('ANSIBLE_VCSIM_CONTAINER'):
            self.image = os.environ.get('ANSIBLE_VCSIM_CONTAINER')
        else:
            self.image = 'quay.io/ansible/vcenter-test-container:1.7.0'

        # VMware tests can be run on govcsim or BYO with a static config file.
        # The simulator is the default if no config is provided.
        self.vmware_test_platform = os.environ.get('VMWARE_TEST_PLATFORM', 'govcsim')

        if self.vmware_test_platform == 'govcsim':
            self.uses_docker = True
            self.uses_config = False
        elif self.vmware_test_platform == 'static':
            self.uses_docker = False
            self.uses_config = True

    def setup(self):
        """Setup the cloud resource before delegation and register a cleanup callback."""
        super(VcenterProvider, self).setup()

        self._set_cloud_config('vmware_test_platform', self.vmware_test_platform)

        if self.vmware_test_platform == 'govcsim':
            self._setup_dynamic_simulator()
            self.managed = True
        elif self.vmware_test_platform == 'static':
            self._use_static_config()
            self._setup_static()
        else:
            raise ApplicationError('Unknown vmware_test_platform: %s' % self.vmware_test_platform)

    def _setup_dynamic_simulator(self):
        """Create a vcenter simulator using docker."""
        ports = [
            443,
            8080,
            8989,
            5000,  # control port for flask app in simulator
        ]

        descriptor = run_support_container(
            self.args,
            self.platform,
            self.image,
            self.DOCKER_SIMULATOR_NAME,
            ports,
            allow_existing=True,
            cleanup=True,
        )

        descriptor.register(self.args)

        self._set_cloud_config('vcenter_hostname', self.DOCKER_SIMULATOR_NAME)

    def _setup_static(self):
        if not os.path.exists(self.config_static_path):
            raise ApplicationError('Configuration file does not exist: %s' % self.config_static_path)


class VcenterEnvironment(CloudEnvironment):
    """VMware vcenter/esx environment plugin. Updates integration test environment after delegation."""
    def get_environment_config(self):
        """
        :rtype: CloudEnvironmentConfig
        """
        try:
            # We may be in a container, so we cannot just reach VMWARE_TEST_PLATFORM,
            # We do a try/except instead
            parser = ConfigParser()
            parser.read(self.config_path)  # static

            env_vars = dict()
            ansible_vars = dict(
                resource_prefix=self.resource_prefix,
            )
            ansible_vars.update(dict(parser.items('DEFAULT', raw=True)))
        except KeyError:  # govcsim
            env_vars = dict(
                VCENTER_HOSTNAME=self._get_cloud_config('vcenter_hostname'),
                VCENTER_USERNAME='user',
                VCENTER_PASSWORD='pass',
            )

            ansible_vars = dict(
                vcsim=self._get_cloud_config('vcenter_hostname'),
                vcenter_hostname=self._get_cloud_config('vcenter_hostname'),
                vcenter_username='user',
                vcenter_password='pass',
            )

        for key, value in ansible_vars.items():
            if key.endswith('_password'):
                display.sensitive.add(value)

        return CloudEnvironmentConfig(
            env_vars=env_vars,
            ansible_vars=ansible_vars,
            module_defaults={
                'group/vmware': {
                    'hostname': ansible_vars['vcenter_hostname'],
                    'username': ansible_vars['vcenter_username'],
                    'password': ansible_vars['vcenter_password'],
                    'port': ansible_vars.get('vcenter_port', '443'),
                    'validate_certs': ansible_vars.get('vmware_validate_certs', 'no'),
                },
            },
        )
