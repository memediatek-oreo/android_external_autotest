# Copyright (c) 2013 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from autotest_lib.client.bin import site_utils, test
from autotest_lib.client.common_lib import error

import dbus
import dbus.types
import os
import time

from autotest_lib.client.cros import backchannel
# Disable warning about flimflam_test_path not being used. It is used to set up
# the path to the flimflam module.
# pylint: disable=W0611
from autotest_lib.client.cros import flimflam_test_path
# pylint: enable=W0611
from autotest_lib.client.cros import network
from autotest_lib.client.cros.cellular import cell_tools
from autotest_lib.client.cros.cellular import mm
from autotest_lib.client.cros.cellular import mm1_constants
from autotest_lib.client.cros.cellular.pseudomodem import pseudomodem_context
import flimflam

I_ACTIVATION_TEST = 'Interface.CDMAActivationTest'
ACTIVATION_STATE_TIMEOUT = 10
MODEM_STATE_TIMEOUT = 10
TEST_MODEMS_MODULE_PATH = os.path.join(os.path.dirname(__file__), 'files',
                                       'modems.py')

class ActivationTest(object):
    """
    Super class that implements setup code that is common to the individual
    tests.

    """
    def __init__(self, test):
        self.test = test
        self.modem_properties_interface = None


    def run(self):
        """
        Restarts the pseudomodem with the modem object to be used for this
        test and runs the test.

        """
        with pseudomodem_context.PseudoModemManagerContext(
                True,
                flags_map=self._pseudomodem_flags()):
            # Give pseudomodem time to settle down
            time.sleep(1)
            self._run_test()


    def _get_modem_properties_interface(self):
        if not self.modem_properties_interface:
            self.modem_properties_interface = \
                    self.test.modem().PropertiesInterface()
        return self.modem_properties_interface


    def _set_modem_activation_state(self, state):
        interface = self._get_modem_properties_interface()
        interface.Set(
                mm1_constants.I_MODEM_CDMA,
                'ActivationState',
                dbus.types.UInt32(state))


    def _get_modem_activation_state(self):
        interface = self._get_modem_properties_interface()
        return interface.Get(mm1_constants.I_MODEM_CDMA,
                             'ActivationState')


    def _pseudomodem_flags(self):
        """
        Subclasses must override this method to setup the flags map passed to
        pseudomodem to suite their needs.

        """
        raise NotImplementedError()


    def _run_test(self):
        raise NotImplementedError()

class ActivationStateTest(ActivationTest):
    """
    This test verifies that the service "ActivationState" property matches the
    cdma activation state exposed by ModemManager.

    """
    def _pseudomodem_flags(self):
        return {'family' : 'CDMA'}


    def _run_test(self):
        network.ResetAllModems(self.test.flim)

        # The modem state should be REGISTERED.
        self.test.check_modem_state(mm1_constants.MM_MODEM_STATE_REGISTERED)

        # Service should appear as 'activated'.
        self.test.check_service_activation_state('activated')

        # Service activation state should change to 'not-activated'.
        self._set_modem_activation_state(
                mm1_constants.MM_MODEM_CDMA_ACTIVATION_STATE_NOT_ACTIVATED)
        self.test.check_service_activation_state('not-activated')

        # Service activation state should change to 'activating'.
        self._set_modem_activation_state(
                mm1_constants.MM_MODEM_CDMA_ACTIVATION_STATE_ACTIVATING)
        self.test.check_service_activation_state('activating')

        # Service activation state should change to 'partially-activated'.
        st = mm1_constants.MM_MODEM_CDMA_ACTIVATION_STATE_PARTIALLY_ACTIVATED
        self._set_modem_activation_state(st)
        self.test.check_service_activation_state('partially-activated')

        # Service activation state should change to 'activated'.
        self._set_modem_activation_state(
                mm1_constants.MM_MODEM_CDMA_ACTIVATION_STATE_ACTIVATED)
        self.test.check_service_activation_state('activated')


class ActivationSuccessTest(ActivationTest):
    """
    This test verifies that the service finally bacomes "activated" when the
    service is told to initiate OTASP activation.

    """
    def _pseudomodem_flags(self):
        return {'test-module' : TEST_MODEMS_MODULE_PATH,
                'test-modem-class' : 'UnactivatedCdmaModem'}


    def _run_test(self):
        network.ResetAllModems(self.test.flim)

        # The modem state should be REGISTERED.
        self.test.check_modem_state(mm1_constants.MM_MODEM_STATE_REGISTERED)

        # Service should appear as 'not-activated'.
        self.test.check_service_activation_state('not-activated')

        # Call 'CompleteActivation' on the service. The service should become
        # 'activating'.
        service = self.test.find_cellular_service()
        service.CompleteCellularActivation()
        self.test.check_service_activation_state('activating')

        # The modem should reset in 5 seconds. Wait 5 more seconds to make sure
        # a new service gets created.
        time.sleep(10)
        self.test.check_service_activation_state('activated')


class ActivationFailureRetryTest(ActivationTest):
    """
    This test verifies that if "ActivateAutomatic" fails, a retry will be
    scheduled.

    """
    NUM_ACTIVATE_RETRIES = 5
    def _pseudomodem_flags(self):
        return {'test-module' : TEST_MODEMS_MODULE_PATH,
                'test-modem-class' : 'ActivationRetryModem',
                'test-modem-arg' : [self.NUM_ACTIVATE_RETRIES]}


    def _run_test(self):
        network.ResetAllModems(self.test.flim)

        # The modem state should be REGISTERED.
        self.test.check_modem_state(mm1_constants.MM_MODEM_STATE_REGISTERED)

        # Service should appear as 'not-activated'.
        self.test.check_service_activation_state('not-activated')

        # Call 'CompleteActivation' on the service. The service should remain
        # 'not-activated'.
        service = self.test.find_cellular_service()
        service.CompleteCellularActivation()

        modem_props = self._get_modem_properties_interface()
        while modem_props.Get(I_ACTIVATION_TEST, 'ActivateCount') < \
            self.NUM_ACTIVATE_RETRIES:
            self.test.check_service_activation_state('not-activated')

        # Activation should succeed after the latest retry.
        self.test.check_service_activation_state('activating')

        # The modem should reset in 5 seconds. Wait 5 more seconds to make sure
        # a new service gets created.
        time.sleep(10)
        self.test.check_service_activation_state('activated')


class network_CDMAActivate(test.test):
    """
    Tests various scenarios that may arise during the post-payment CDMA
    activation process when shill accesses the modem via ModemManager.

    """
    version = 1

    def modem(self):
        """
        Returns a D-Bus proxy for the current modem object exposed by the
        modem manager.

        @return A dbus.service.Object instance.

        """
        manager, modem_path  = mm.PickOneModem('')
        return manager.GetModem(modem_path)


    def modem_state(self):
        """
        Gets the current modem state from the current modem manager.

        @return The modem state, as a uint32 value.

        """
        modem = self.modem()
        props = modem.GetAll(mm1_constants.I_MODEM)
        return props['State']


    def check_modem_state(self, expected_state, timeout=MODEM_STATE_TIMEOUT):
        """
        Polls until the modem has the expected state within |timeout| seconds.

        @param expected_state: The modem state the modem is expected to be in.
        @param timeout: The timeout interval for polling.

        @raises error.TestFail, if the modem doesn't transition to
                |expected_state| within |timeout|.

        """
        site_utils.poll_for_condition(
            lambda: self.modem_state() == expected_state,
            exception=error.TestFail('Timed out waiting for modem state ' +
                                     str(expected_state)),
            timeout=timeout);


    def find_cellular_service(self):
        """
        Searches for a cellular service and returns it.

        @return A dbus.service.Object instance.
        @raises error.TestFail, if no cellular service is found.

        """
        service = self.flim.FindCellularService()
        if not service:
            raise error.TestFail('Could not find cellular service.')
        return service


    def check_service_activation_state(self, expected_state):
        """
        Waits until the current cellular service has the expected activation
        state within ACTIVATION_STATE_TIMEOUT seconds.

        @param expected_state: The activation state the service is expected to
                               be in.
        @raises error.TestFail, if no cellular service is found or the service
                activation state doesn't match |expected_state| within timeout.

        """
        service = self.find_cellular_service()
        state = self.flim.WaitForServiceState(
            service=service,
            expected_states=[expected_state],
            timeout=ACTIVATION_STATE_TIMEOUT,
            property_name='Cellular.ActivationState')[0]
        if state != expected_state:
            raise error.TestFail(
                    'Service activation state should be \'%s\', but it is '
                    '\'%s\'.' % (expected_state, state))


    def run_once(self):
        with backchannel.Backchannel():
            self.flim = flimflam.FlimFlam()
            self.device_manager = flimflam.DeviceManager(self.flim)
            self.flim.SetDebugTags(
                    'dbus+service+device+modem+cellular+portal+network+'
                    'manager+dhcp')

            tests = [
                ActivationStateTest(self),
                ActivationSuccessTest(self),
                ActivationFailureRetryTest(self)
            ]

            with cell_tools.OtherDeviceShutdownContext('cellular'):
                for test in tests:
                    test.run()
