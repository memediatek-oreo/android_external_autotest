# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging

from autotest_lib.client.common_lib import error
from autotest_lib.client.cros.enterprise import enterprise_policy_base


class policy_BlockThirdPartyCookies(
        enterprise_policy_base.EnterprisePolicyTest):
    """
    Test effect of BlockThirdPartyCookies policy on Chrome OS behavior.

    This test verifies the behaviour and appearance of the 'Block third-party
    cookies...' check box setting on the 'chrome://settings page for all valid
    values of the BlockThirdPartyCookies user policy: True, False, and Not set.
    The corresponding test cases are True_Block, False_Allow, and NotSet_Allow.

    """
    version = 1

    POLICY_NAME = 'BlockThirdPartyCookies'
    TEST_CASES = {
        'True_Block': True,
        'False_Allow': False,
        'NotSet_Allow': None
    }
    SUPPORTING_POLICIES = {
        'DefaultCookiesSetting': 1}


    def _test_block_3rd_party_cookies(self, policy_value, policies_dict):
        """
        Verify CrOS enforces BlockThirdPartyCookies policy value.

        When BlockThirdPartyCookies policy is set true (false), then the
        'Block third-party cookies...' check box shall be (un)checked. When
        set either True or False, then the check box shall be uneditable.
        When Not set, then the check box shall be editable.

        @param policy_value: policy value expected on chrome://policy page.
        @param policies_dict: policy dict data sent to the fake DM server.
        @raises: TestFail if setting is incorrectly (un)checked or
                 (un)editable, based on the policy value.

        """
        logging.info('Running _test_block_3rd_party_cookies(%s, %s)',
                     policy_value, policies_dict)
        self.setup_case(self.POLICY_NAME, policy_value, policies_dict)

        # Get check box status from the settings page.
        setting_pref = 'profile.block_third_party_cookies'
        properties = self._get_settings_checkbox_properties(setting_pref)
        setting_label = properties[self.SETTING_LABEL]
        setting_is_checked = properties[self.SETTING_CHECKED]
        setting_is_disabled = properties[self.SETTING_DISABLED]

        # Setting shall be checked if policy is set True, unchecked if False.
        if policy_value == 'true' and not setting_is_checked:
            raise error.TestFail('Block 3rd-party cookies setting should be '
                                 'checked.')
        if policy_value == 'false' and setting_is_checked:
            raise error.TestFail('Block 3rd-party cookies setting should be '
                                 'unchecked.')

        # Setting shall be enabled if policy is Not set, disabled if set.
        if policy_value == 'null':
            if setting_is_disabled:
                raise error.TestFail('Block 3rd-party cookies setting should '
                                     'be editable.')
        else:
            if not setting_is_disabled:
                raise error.TestFail('Block 3rd-party cookies setting should '
                                     'be uneditable.')


    def run_test_case(self, case):
        """
        Setup and run the test configured for the specified test case.

        Set the expected |policy_value| and |policies_dict| data defined for
        the specified test |case|, and run the test.

        @param case: Name of the test case to run.

        """
        policy_value = self.packed_json_string(self.TEST_CASES[case])
        policy_dict = {self.POLICY_NAME: self.TEST_CASES[case]}
        policies_dict = self.SUPPORTING_POLICIES.copy()
        policies_dict.update(policy_dict)
        self._test_block_3rd_party_cookies(policy_value, policies_dict)
