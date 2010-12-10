# Copyright (c) 2010 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import logging, os, re, time
from autotest_lib.client.bin import utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.cros import ui_test

class graphics_WindowManagerGraphicsCapture(ui_test.UITest):
    version = 1

    def setup(self):
        self.job.setup_dep(['glbench'])

    def run_once(self):
        dep = 'glbench'
        dep_dir = os.path.join(self.autodir, 'deps', dep)
        self.job.install_pkg(dep, 'dep', dep_dir)

        screenshot1_reference = os.path.join(self.bindir,
                                            "screenshot1_reference")
        screenshot1_generated = os.path.join(self.resultsdir,
                                            "screenshot1_generated")
        screenshot1_resized = os.path.join(self.resultsdir,
                                            "screenshot1_generated_resized")
        screenshot2_reference = os.path.join(self.bindir,
                                            "screenshot2_reference")
        screenshot2_generated = os.path.join(self.resultsdir,
                                            "screenshot2_generated")
        screenshot2_resized = os.path.join(self.resultsdir,
                                            "screenshot2_generated_resized")

        exefile = os.path.join(self.autodir, 'deps/glbench/windowmanagertest')
        # Enable running in window manager
        exefile = ('chvt 1 && DISPLAY=:0 XAUTHORITY=/home/chronos/.Xauthority ' 
                   + exefile)

        # Delay before screenshot: 1 second has caused failures 
        options = ' --screenshot1_sec 2'
        options += ' --screenshot2_sec 1'
        options += ' --cooldown_sec 1'
        options += ' --screenshot1_cmd "screenshot %s"' % screenshot1_generated
        options += ' --screenshot2_cmd "screenshot %s"' % screenshot2_generated

        utils.system(exefile + " " + options)

        utils.system("convert -resize '100x100!' %s %s" %
                     (screenshot1_generated, screenshot1_resized))
        utils.system("convert -resize '100x100!' %s %s" %
                     (screenshot2_generated, screenshot2_resized))
        os.remove(screenshot1_generated)
        os.remove(screenshot2_generated)

        utils.system("perceptualdiff -verbose %s %s"
                     % (screenshot1_reference, screenshot1_resized))
        utils.system("perceptualdiff -verbose %s %s"
                     % (screenshot2_reference, screenshot2_resized))
