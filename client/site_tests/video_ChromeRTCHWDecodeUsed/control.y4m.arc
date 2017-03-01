# Copyright 2016 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

AUTHOR = "Chrome OS Project, chromeos-video@google.com"
NAME = "video_ChromeRTCHWDecodeUsed.arc"
PURPOSE = "Verify that HW decoding works for WebRTC/vp8 video."
ATTRIBUTES = "suite:arc-bvt-cq, suite:bvt-perbuild"
TIME = "SHORT"
TEST_CATEGORY = "General"
TEST_CLASS = "video"
TEST_TYPE = "client"
DEPENDENCIES = "hw_video_acc_vp8, arc"
JOB_RETRIES = 2
BUG_TEMPLATE = {
    'labels': ['OS-Chrome', 'VideoTestFailure'],
    'cc': ['chromeos-video-test-failures@google.com'],
}
ARC_MODE = "enabled"

DOC = """
This test verifies that HW decoding works for WebRTC/vp8 video.
"""

job.run_test('video_ChromeRTCHWDecodeUsed',
             video_name='crowd720_25frames.y4m',
             histogram_name='Media.RTCVideoDecoderInitDecodeSucces',
             histogram_bucket_val=1,
             arc_mode=ARC_MODE)
