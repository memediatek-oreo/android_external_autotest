# Copyright 2015 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import glob
import logging
import os
import pipes
import re
import shutil
import subprocess
import sys
import tempfile

from autotest_lib.client.bin import test, utils
from autotest_lib.client.common_lib import error
from autotest_lib.client.common_lib.cros import chrome, arc_common

_ADB_KEYS_PATH = '/tmp/adb_keys'
_ADB_VENDOR_KEYS = 'ADB_VENDOR_KEYS'
_ANDROID_CONTAINER_PID_PATH = '/var/run/containers/android_*/container.pid'
_SCREENSHOT_DIR_PATH = '/var/log/arc-screenshots'
_SCREENSHOT_BASENAME = 'arc-screenshot'
_MAX_SCREENSHOT_NUM = 10
_SDCARD_PID_PATH = '/var/run/arc/sdcard.pid'
_ANDROID_ADB_KEYS_PATH = '/data/misc/adb/adb_keys'
_PROCESS_CHECK_INTERVAL_SECONDS = 1
_WAIT_FOR_ADB_READY = 60
_WAIT_FOR_ANDROID_PROCESS_SECONDS = 60
_WAIT_FOR_DATA_MOUNTED_SECONDS = 60
_VAR_LOGCAT_PATH = '/var/log/logcat'


def setup_adb_host():
    """Setup ADB host keys.

    This sets up the files and environment variables that wait_for_adb_ready()
    needs"""
    if _ADB_VENDOR_KEYS in os.environ:
        return
    if not os.path.exists(_ADB_KEYS_PATH):
        os.mkdir(_ADB_KEYS_PATH)
    # adb expects $HOME to be writable.
    os.environ['HOME'] = _ADB_KEYS_PATH

    # Generate and save keys for adb if needed
    key_path = os.path.join(_ADB_KEYS_PATH, 'test_key')
    if not os.path.exists(key_path):
        utils.system('adb keygen ' + pipes.quote(key_path))
    os.environ[_ADB_VENDOR_KEYS] = key_path


def adb_connect():
    """Attempt to connect ADB to the Android container.

    Returns true if successful. Do not call this function directly. Call
    wait_for_adb_ready() instead."""
    if not is_android_booted():
        return False
    if utils.system('adb connect localhost:22', ignore_status=True) != 0:
        return False
    return is_adb_connected()


def is_adb_connected():
    """Return true if adb is connected to the container."""
    output = utils.system_output('adb get-state', ignore_status=True)
    logging.debug('adb get-state: %s', output)
    return output.strip() == 'device'


def is_partial_boot_enabled():
    """Return true if partial boot is enabled.

    When partial boot is enabled, Android is started at login screen without
    any persistent state (e.g. /data is not mounted).
    """
    return _android_shell('getprop ro.boot.partial_boot') == '1'


def _is_android_data_mounted():
    """Return true if Android's /data is mounted with partial boot enabled."""
    return _android_shell('getprop ro.data_mounted') == '1'


def _wait_for_data_mounted(timeout=_WAIT_FOR_DATA_MOUNTED_SECONDS):
    utils.poll_for_condition(
            condition=_is_android_data_mounted,
            desc='Wait for /data mounted',
            timeout=timeout,
            sleep_interval=_PROCESS_CHECK_INTERVAL_SECONDS)


def wait_for_adb_ready(timeout=_WAIT_FOR_ADB_READY):
    """Wait for the ADB client to connect to the ARC container.

    @param timeout: Timeout in seconds.
    """
    # When partial boot is enabled, although adbd is started at login screen,
    # we still need /data to be mounted to set up key-based authentication.
    # /data should be mounted once the user has logged in.
    if is_partial_boot_enabled():
        _wait_for_data_mounted()

    setup_adb_host()
    if is_adb_connected():
      return

    # Push keys for adb.
    pubkey_path = os.environ[_ADB_VENDOR_KEYS] + '.pub'
    with open(pubkey_path, 'r') as f:
        _write_android_file(_ANDROID_ADB_KEYS_PATH, f.read())
    _android_shell('restorecon ' + pipes.quote(_ANDROID_ADB_KEYS_PATH))

    # This starts adbd.
    _android_shell('setprop sys.usb.config mtp,adb')

    # Kill existing adb server to ensure that a full reconnect is performed.
    utils.system('adb kill-server', ignore_status=True)

    exception = error.TestFail('adb is not ready in %d seconds.' % timeout)
    utils.poll_for_condition(adb_connect,
                             exception,
                             timeout)


def grant_permissions(package, permissions):
    """Grants permissions to a package.

    @param package: Package name.
    @param permissions: A list of permissions.

    """
    for permission in permissions:
        adb_shell('pm grant %s android.permission.%s' % (
                  pipes.quote(package), pipes.quote(permission)))


def adb_cmd(cmd, **kwargs):
    """Executed cmd using adb. Must wait for adb ready.

    @param cmd: Command to run.
    """
    wait_for_adb_ready()
    return utils.system_output('adb %s' % cmd, **kwargs)


def adb_shell(cmd, **kwargs):
    """Executed shell command with adb.

    @param cmd: Command to run.
    """
    output = adb_cmd('shell %s' % pipes.quote(cmd), **kwargs)
    # Some android commands include a trailing CRLF in their output.
    if kwargs.pop('strip_trailing_whitespace', True):
      output = output.rstrip()
    return output


def adb_install(apk):
    """Install an apk into container. You must connect first.

    @param apk: Package to install.
    """
    return adb_cmd('install -r %s' % apk)


def adb_uninstall(apk):
    """Remove an apk from container. You must connect first.

    @param apk: Package to uninstall.
    """
    return adb_cmd('uninstall %s' % apk)


def adb_reboot():
    """Reboots the container. You must connect first."""
    adb_root()
    return adb_cmd('reboot', ignore_status=True)


def adb_root():
    """Restart adbd with root permission."""
    adb_cmd('root')


def get_container_root():
    """Returns path to Android container root directory.

    Raises:
      TestError if no container root directory is found, or
      more than one container root directories are found.
    """
    # Find the PID file rather than the android_XXXXXX/ directory to ignore
    # stale and empty android_XXXXXX/ directories when they exist.
    # TODO(yusukes): Investigate why libcontainer sometimes fails to remove
    # the directory. See b/63376749 for more details.
    arc_container_pid_files = glob.glob(_ANDROID_CONTAINER_PID_PATH)

    if len(arc_container_pid_files) == 0:
        raise error.TestError('Android container not available')

    if len(arc_container_pid_files) > 1:
        raise error.TestError('Multiple Android containers found: %r. '
                              'Reboot your DUT to recover.' % (
                                  arc_container_pid_files))

    return os.path.dirname(arc_container_pid_files[0])


def get_job_pid(job_name):
    """Returns the PID of an upstart job."""
    status = utils.system_output('status %s' % job_name)
    match = re.match(r'^%s start/running, process (\d+)$' % job_name,
                     status)
    if not match:
        raise error.TestError('Unexpected status: "%s"' % status)
    return match.group(1)


def get_container_pid():
    """Returns the PID of the container."""
    container_root = get_container_root()
    pid_path = os.path.join(container_root, 'container.pid')
    return utils.read_one_line(pid_path)


def get_sdcard_pid():
    """Returns the PID of the sdcard container."""
    return utils.read_one_line(_SDCARD_PID_PATH)


def get_removable_media_pid():
    """Returns the PID of the arc-removable-media FUSE daemon."""
    job_pid = get_job_pid('arc-removable-media')
    # |job_pid| is the minijail process, obtain the PID of the process running
    # inside the mount namespace.
    # FUSE process is the only process running as chronos in the process group.
    return utils.system_output('pgrep -u chronos -g %s' % job_pid)


def get_obb_mounter_pid():
    """Returns the PID of the OBB mounter."""
    return utils.system_output('pgrep -f -u root ^/usr/bin/arc-obb-mounter')


def is_android_booted():
    """Return whether Android has completed booting."""
    # We used to check sys.boot_completed system property to detect Android has
    # booted in Android M, but in Android N it is set long before BOOT_COMPLETED
    # intent is broadcast. So we read event logs instead.
    log = _android_shell(
        'logcat -d -b events *:S arc_system_event', ignore_status=True)
    return 'ArcAppLauncher:started' in log


def is_android_process_running(process_name):
    """Return whether Android has completed booting.

    @param process_name: Process name.
    """
    output = adb_shell('ps | grep %s' % pipes.quote(' %s$' % process_name))
    return bool(output)


def check_android_file_exists(filename):
    """Checks whether the given file exists in the Android filesystem

    @param filename: File to check.
    """
    return adb_shell('test -e {} && echo FileExists'.format(
            pipes.quote(filename))).find("FileExists") >= 0


def read_android_file(filename):
    """Reads a file in Android filesystem.

    @param filename: File to read.
    """
    with tempfile.NamedTemporaryFile() as tmpfile:
        adb_cmd('pull %s %s' % (pipes.quote(filename),
                                pipes.quote(tmpfile.name)))
        with open(tmpfile.name) as f:
            return f.read()

    return None


def write_android_file(filename, data):
    """Writes to a file in Android filesystem.

    @param filename: File to write.
    @param data: Data to write.
    """
    with tempfile.NamedTemporaryFile() as tmpfile:
        tmpfile.write(data)
        tmpfile.flush()

        adb_cmd('push %s %s' % (pipes.quote(tmpfile.name),
                                pipes.quote(filename)))


def _write_android_file(filename, data):
    """Writes to a file in Android filesystem.

    This is an internal function used to bootstrap adb.
    Tests should use write_android_file instead.
    """
    android_cmd = 'cat > %s' % pipes.quote(filename)
    cros_cmd = 'android-sh -c %s' % pipes.quote(android_cmd)
    utils.run(cros_cmd, stdin=data)


def remove_android_file(filename):
    """Removes a file in Android filesystem.

    @param filename: File to remove.
    """
    adb_shell('rm -f %s' % pipes.quote(filename))


def wait_for_android_boot(timeout=None):
    """Sleep until Android has completed booting or timeout occurs.

    @param timeout: Timeout in seconds.
    """
    arc_common.wait_for_android_boot(timeout)


def wait_for_android_process(process_name,
                             timeout=_WAIT_FOR_ANDROID_PROCESS_SECONDS):
    """Sleep until an Android process is running or timeout occurs.

    @param process_name: Process name.
    @param timeout: Timeout in seconds.
    """
    condition = lambda: is_android_process_running(process_name)
    utils.poll_for_condition(condition=condition,
                             desc='%s is running' % process_name,
                             timeout=timeout,
                             sleep_interval=_PROCESS_CHECK_INTERVAL_SECONDS)


def _android_shell(cmd, **kwargs):
    """Execute cmd instead the Android container.

    This function is strictly for internal use only, as commands do not run in a
    fully consistent Android environment. Prefer adb_shell instead.
    """
    return utils.system_output('android-sh -c {}'.format(pipes.quote(cmd)),
                               **kwargs)


def is_android_container_alive():
    """Check if android container is alive."""
    try:
        container_pid = get_container_pid()
    except Exception, e:
        logging.error('is_android_container_alive failed: %r', e)
        return False
    return utils.pid_is_alive(int(container_pid))


def is_package_installed(package):
    """Check if a package is installed. adb must be ready.

    @param package: Package in request.
    """
    packages = adb_shell('pm list packages').splitlines()
    package_entry = 'package:{}'.format(package)
    return package_entry in packages


def _before_iteration_hook(obj):
    """Executed by parent class before every iteration.

    This function resets the run_once_finished flag before every iteration
    so we can detect failure on every single iteration.

    Args:
        obj: the test itself
    """
    obj.run_once_finished = False


def _after_iteration_hook(obj):
    """Executed by parent class after every iteration.

    The parent class will handle exceptions and failures in the run and will
    always call this hook afterwards. Take a screenshot if the run has not
    been marked as finished (i.e. there was a failure/exception).

    Args:
        obj: the test itself
    """
    if not obj.run_once_finished:
        if not os.path.exists(_SCREENSHOT_DIR_PATH):
            os.mkdir(_SCREENSHOT_DIR_PATH, 0755)
        obj.num_screenshots += 1
        if obj.num_screenshots <= _MAX_SCREENSHOT_NUM:
            logging.warning('Iteration %d failed, taking a screenshot.',
                            obj.iteration)
            from cros.graphics.gbm import crtcScreenshot
            try:
                image = crtcScreenshot()
                image.save('{}/{}_iter{}.png'.format(_SCREENSHOT_DIR_PATH,
                                                     _SCREENSHOT_BASENAME,
                                                     obj.iteration))
            except Exception:
                e = sys.exc_info()[0]
                logging.warning('Unable to capture screenshot. %s' % e)
        else:
            logging.warning('Too many failures, no screenshot taken')


def send_keycode(keycode):
    """Sends the given keycode to the container

    @param keycode: keycode to send.
    """
    adb_shell('input keyevent {}'.format(keycode))


def get_android_sdk_version():
    """Returns the Android SDK version.

    This function can be called before Android container boots.
    """
    with open('/etc/lsb-release') as f:
        values = dict(line.split('=', 1) for line in f.read().splitlines())
    try:
        return int(values['CHROMEOS_ARC_ANDROID_SDK_VERSION'])
    except (KeyError, ValueError):
        raise error.TestError('Could not determine Android SDK version')


class ArcTest(test.test):
    """ Base class of ARC Test.

    This class could be used as super class of an ARC test for saving
    redundant codes for container bringup, autotest-dep package(s) including
    uiautomator setup if required, and apks install/remove during
    arc_setup/arc_teardown, respectively. By default arc_setup() is called in
    initialize() after Android have been brought up. It could also be overridden
    to perform non-default tasks. For example, a simple ArcHelloWorldTest can be
    just implemented with print 'HelloWorld' in its run_once() and no other
    functions are required. We could expect ArcHelloWorldTest would bring up
    browser and  wait for container up, then print 'Hello World', and shutdown
    browser after. As a precaution, if you overwrite initialize(), arc_setup(),
    or cleanup() function(s) in ARC test, remember to call the corresponding
    function(s) in this base class as well.

    """
    version = 1
    _PKG_UIAUTOMATOR = 'uiautomator'
    _FULL_PKG_NAME_UIAUTOMATOR = 'com.github.uiautomator'

    def __init__(self, *args, **kwargs):
        """Initialize flag setting."""
        super(ArcTest, self).__init__(*args, **kwargs)
        self.initialized = False
        # Set the flag run_once_finished to detect if a test is executed
        # successfully without any exception thrown. Otherwise, generate
        # a screenshot in /var/log for debugging.
        self.run_once_finished = False
        self.logcat_proc = None
        self.dep_package = None
        self.apks = None
        self.full_pkg_names = []
        self.uiautomator = False
        self.email_id = None
        self.password = None
        self._chrome = None
        if os.path.exists(_SCREENSHOT_DIR_PATH):
            shutil.rmtree(_SCREENSHOT_DIR_PATH)
        self.register_before_iteration_hook(_before_iteration_hook)
        self.register_after_iteration_hook(_after_iteration_hook)
        # Keep track of the number of debug screenshots taken and keep the
        # total number sane to avoid issues.
        self.num_screenshots = 0

    def initialize(self, extension_path=None,
                   arc_mode=arc_common.ARC_MODE_ENABLED, **chrome_kargs):
        """Log in to a test account."""
        extension_paths = [extension_path] if extension_path else []
        self._chrome = chrome.Chrome(extension_paths=extension_paths,
                                     arc_mode=arc_mode,
                                     **chrome_kargs)
        if extension_path:
            self._extension = self._chrome.get_extension(extension_path)
        else:
            self._extension = None
        # With ARC enabled, Chrome will wait until container to boot up
        # before returning here, see chrome.py.
        self.initialized = True
        try:
            if is_android_container_alive():
                self.arc_setup()
            else:
                logging.error('Container is alive?')
        except Exception as err:
            self.cleanup()
            raise error.TestFail(err)

    def after_run_once(self):
        """Executed after run_once() only if there were no errors.

        This function marks the run as finished with a flag. If there was a
        failure the flag won't be set and the failure can then be detected by
        testing the run_once_finished flag.
        """
        logging.info('After run_once')
        self.run_once_finished = True

    def cleanup(self):
        """Log out of Chrome."""
        if not self.initialized:
            logging.info('Skipping ARC cleanup: not initialized')
            return
        logging.info('Starting ARC cleanup')
        try:
            if is_android_container_alive():
                self.arc_teardown()
        except Exception as err:
            raise error.TestFail(err)
        finally:
            try:
                self._stop_logcat()
            finally:
                if self._chrome is not None:
                    self._chrome.close()

    def arc_setup(self, dep_package=None, apks=None, full_pkg_names=None,
                  uiautomator=False, email_id=None, password=None,
                  block_outbound=False):
        """ARC test setup: Setup dependencies and install apks.

        This function disables package verification and enables non-market
        APK installation. Then, it installs specified APK(s) and uiautomator
        package and path if required in a test.

        @param dep_package: Package name of autotest_deps APK package.
        @param apks: Array of APK names to be installed in dep_package.
        @param full_pkg_names: Array of full package names to be removed
                               in teardown.
        @param uiautomator: uiautomator python package is required or not.

        @param email_id: email id to be attached to the android. Only used
                         when  account_util is set to true.
        @param password: password related to the email_id.
        @param block_outbound: block outbound network traffic during a test.
        """
        if not self.initialized:
            logging.info('Skipping ARC setup: not initialized')
            return
        logging.info('Starting ARC setup')
        self.dep_package = dep_package
        self.apks = apks
        self.uiautomator = uiautomator
        self.email_id = email_id
        self.password = password
        # Setup dependent packages if required
        packages = []
        if dep_package:
            packages.append(dep_package)
        if self.uiautomator:
            packages.append(self._PKG_UIAUTOMATOR)
        if packages:
            logging.info('Setting up dependent package(s) %s', packages)
            self.job.setup_dep(packages)

        # TODO(b/29341443): Run logcat on non ArcTest test cases too.
        with open(_VAR_LOGCAT_PATH, 'w') as f:
            self.logcat_proc = subprocess.Popen(
                ['android-sh', '-c', 'logcat -v threadtime'],
                stdout=f,
                stderr=subprocess.STDOUT,
                close_fds=True)

        wait_for_adb_ready()

        # package_verifier_user_consent == -1 means to reject Google's
        # verification on the server side through Play Store.  This suppress a
        # consent dialog from the system.
        adb_shell('settings put secure package_verifier_user_consent -1')
        adb_shell('settings put global package_verifier_enable 0')
        adb_shell('settings put secure install_non_market_apps 1')

        if self.dep_package:
            apk_path = os.path.join(self.autodir, 'deps', self.dep_package)
            if self.apks:
                for apk in self.apks:
                    logging.info('Installing %s', apk)
                    adb_install('%s/%s' % (apk_path, apk))
                # Verify if package(s) are installed correctly
                if not full_pkg_names:
                    raise error.TestError('Package names of apks expected')
                for pkg in full_pkg_names:
                    logging.info('Check if %s is installed', pkg)
                    if not is_package_installed(pkg):
                        raise error.TestError('Package %s not found' % pkg)
                    # Make sure full_pkg_names contains installed packages only
                    # so arc_teardown() knows what packages to uninstall.
                    self.full_pkg_names.append(pkg)

        if self.uiautomator:
            path = os.path.join(self.autodir, 'deps', self._PKG_UIAUTOMATOR)
            sys.path.append(path)
        if block_outbound:
            self.block_outbound()

    def _stop_logcat(self):
        """Stop the adb logcat process gracefully."""
        if not self.logcat_proc:
            return
        # Running `adb kill-server` should have killed `adb logcat`
        # process, but just in case also send termination signal.
        self.logcat_proc.terminate()

        class TimeoutException(Exception):
            """Termination timeout timed out."""

        try:
            utils.poll_for_condition(
                condition=lambda: self.logcat_proc.poll() is not None,
                exception=TimeoutException,
                timeout=10,
                sleep_interval=0.1,
                desc='Waiting for adb logcat to terminate')
        except TimeoutException:
            logging.info('Killing adb logcat due to timeout')
            self.logcat_proc.kill()
            self.logcat_proc.wait()

    def arc_teardown(self):
        """ARC test teardown.

        This function removes all installed packages in arc_setup stage
        first. Then, it restores package verification and disables non-market
        APK installation.

        """
        if self.full_pkg_names:
            for pkg in self.full_pkg_names:
                logging.info('Uninstalling %s', pkg)
                if not is_package_installed(pkg):
                    raise error.TestError('Package %s was not installed' % pkg)
                adb_uninstall(pkg)
        if self.uiautomator:
            logging.info('Uninstalling %s', self._FULL_PKG_NAME_UIAUTOMATOR)
            adb_uninstall(self._FULL_PKG_NAME_UIAUTOMATOR)
        adb_shell('settings put secure install_non_market_apps 0')
        adb_shell('settings put global package_verifier_enable 1')
        adb_shell('settings put secure package_verifier_user_consent 0')

        remove_android_file(_ANDROID_ADB_KEYS_PATH)
        utils.system_output('adb kill-server')

    def block_outbound(self):
        """ Blocks the connection from the container to outer network.

            The iptables settings accept only 100.115.92.2 port 5555 (adb) and
            all local connections, e.g. uiautomator.
        """
        logging.info('Blocking outbound connection')
        _android_shell('iptables -I OUTPUT -j REJECT')
        _android_shell('iptables -I OUTPUT -p tcp -s 100.115.92.2 --sport 5555 '
                       '-j ACCEPT')
        _android_shell('iptables -I OUTPUT -p tcp -d localhost -j ACCEPT')

    def unblock_outbound(self):
        """ Unblocks the connection from the container to outer network.

            The iptables settings are not permanent which means they reset on
            each instance invocation. But we can still use this function to
            unblock the outbound connections during the test if needed.
        """
        logging.info('Unblocking outbound connection')
        _android_shell('iptables -D OUTPUT -p tcp -d localhost -j ACCEPT')
        _android_shell('iptables -D OUTPUT -p tcp -s 100.115.92.2 --sport 5555 '
                       '-j ACCEPT')
        _android_shell('iptables -D OUTPUT -j REJECT')
