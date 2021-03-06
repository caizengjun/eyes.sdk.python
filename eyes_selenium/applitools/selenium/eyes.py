from __future__ import absolute_import

import base64
import contextlib
import typing

# noinspection PyProtectedMember
from applitools.core import logger
from applitools.core.errors import EyesError
from applitools.core.eyes_base import EyesBase
from applitools.core.geometry import Region
from applitools.core.match_window_task import MatchWindowTask
from applitools.core.scaling import ContextBasedScaleProvider, FixedScaleProvider
from applitools.core.triggers import MouseTrigger, TextTrigger
from applitools.core.utils import image_utils
from selenium.common.exceptions import WebDriverException
from selenium.webdriver.remote.webdriver import WebDriver as RemoteWebDriver

from . import eyes_selenium_utils
from .__version__ import __version__
from .capture import EyesWebDriverScreenshot, dom_capture
from .positioning import ElementPositionProvider, StitchMode
from .target import Target
from .webdriver import EyesWebDriver

if typing.TYPE_CHECKING:
    from typing import Text, Optional
    from applitools.core.scaling import ScaleProvider
    from applitools.core.utils.custom_types import (
        ViewPort,
        AnyWebDriver,
        FrameReference,
        AnyWebElement,
    )


class ScreenshotType(object):
    ENTIRE_ELEMENT_SCREENSHOT = "EntireElementScreenshot"
    REGION_OR_ELEMENT_SCREENSHOT = "RegionOrElementScreenshot"
    FULLPAGE_SCREENSHOT = "FullPageScreenshot"
    VIEWPORT_SCREENSHOT = "ViewportScreenshot"


class Eyes(EyesBase):
    """
    Applitools Selenium Eyes API for python.
    """

    _UNKNOWN_DEVICE_PIXEL_RATIO = 0
    _DEFAULT_DEVICE_PIXEL_RATIO = 1

    @staticmethod
    def set_viewport_size(driver, size):
        # type: (AnyWebDriver, ViewPort) -> None
        eyes_selenium_utils.set_viewport_size(driver, size)

    @staticmethod
    def get_viewport_size(driver):
        # type: (AnyWebDriver) -> ViewPort
        return eyes_selenium_utils.get_viewport_size(driver)

    def _get_viewport_size(self):
        return self.get_viewport_size(self._driver)

    def _set_viewport_size(self, size):
        self.set_viewport_size(self._driver, size)

    def __init__(self, server_url=None):
        super(Eyes, self).__init__(server_url)

        self._driver = None  # type: Optional[AnyWebDriver]
        self._match_window_task = None  # type: Optional[MatchWindowTask]
        self._viewport_size = None  # type: Optional[ViewPort]
        self._screenshot_type = None  # type: Optional[str]  # ScreenshotType
        self._device_pixel_ratio = self._UNKNOWN_DEVICE_PIXEL_RATIO
        self._stitch_mode = StitchMode.Scroll  # type: Text
        self._element_position_provider = (
            None
        )  # type: Optional[ElementPositionProvider]

        # If true, Eyes will create a full page screenshot (by using stitching)
        # for browsers which only returns the viewport screenshot.
        self.force_full_page_screenshot = False  # type: bool

        # If true, Eyes will remove the scrollbars from the pages
        # before taking the screenshot.
        self.hide_scrollbars = False  # type: bool

        # The number of milliseconds to wait before each time a screenshot is taken.
        self.wait_before_screenshots = (
            EyesBase._DEFAULT_WAIT_BEFORE_SCREENSHOTS
        )  # type: int

    @property
    def _seconds_to_wait_screenshot(self):
        return self.wait_before_screenshots / 1000.0

    @property
    def base_agent_id(self):
        return "eyes.selenium.python/{version}".format(version=__version__)

    @property
    def stitch_mode(self):
        # type: () -> Text
        """
        Gets the stitch mode.

        :return: The stitch mode.
        """
        return self._stitch_mode

    @stitch_mode.setter
    def stitch_mode(self, stitch_mode):
        # type: (Text) -> None
        """
        Sets the stitch property - default is by scrolling.

        :param stitch_mode: The stitch mode to set - either scrolling or css.
        """
        self._stitch_mode = stitch_mode
        if stitch_mode == StitchMode.CSS:
            self.hide_scrollbars = True
            self.send_dom = True

    @property
    def driver(self):
        # type: () -> EyesWebDriver
        """
        Returns the current web driver.
        """
        return self._driver

    def _obtain_screenshot_type(
        self,
        is_element,
        inside_a_frame,
        stitch_content,
        force_fullpage,
        is_region=False,
    ):
        # type:(bool, bool, bool, bool, bool) -> str
        if stitch_content or force_fullpage:
            if is_element and not stitch_content:
                return ScreenshotType.REGION_OR_ELEMENT_SCREENSHOT

            if not inside_a_frame:
                if (force_fullpage and not stitch_content) or (
                    stitch_content and not is_element
                ):
                    return ScreenshotType.FULLPAGE_SCREENSHOT

            if inside_a_frame or stitch_content:
                return ScreenshotType.ENTIRE_ELEMENT_SCREENSHOT

        else:
            if is_region or (is_element and not stitch_content):
                return ScreenshotType.REGION_OR_ELEMENT_SCREENSHOT

            if not stitch_content and not force_fullpage:
                return ScreenshotType.VIEWPORT_SCREENSHOT

        return ScreenshotType.VIEWPORT_SCREENSHOT

    @property
    def _environment(self):
        os = self.host_os
        # If no host OS was set, check for mobile OS.
        if os is None:
            logger.info("No OS set, checking for mobile OS...")
            # Since in Python Appium driver is the same for Android and iOS,
            # we need to use the desired capabilities to figure this out.
            if eyes_selenium_utils.is_mobile_device(self._driver):
                platform_name = self._driver.platform_name
                logger.info(platform_name + " detected")
                platform_version = self._driver.platform_version
                if platform_version is not None:
                    # Notice that Python's "split" function's +limit+ is the the
                    # maximum splits performed whereas in Ruby it is the maximum
                    # number of elements in the result (which is why they are set
                    # differently).
                    major_version = platform_version.split(".", 1)[0]
                    os = platform_name + " " + major_version
                else:
                    os = platform_name
                logger.info("Setting OS: " + os)
            else:
                logger.info("No mobile OS detected.")
        app_env = {
            "os": os,
            "hostingApp": self.host_app,
            "displaySize": self._viewport_size,
            "inferred": self._inferred_environment,
        }
        return app_env

    @property
    def _title(self):
        if self._should_get_title:
            # noinspection PyBroadException
            try:
                return self._driver.title
            except Exception:
                self._should_get_title = (
                    False
                )  # Couldn't get _title, return empty string.
        return ""

    @property
    def _inferred_environment(self):
        # type: () -> Optional[Text]
        try:
            user_agent = self._driver.execute_script("return navigator.userAgent")
        except WebDriverException:
            user_agent = None
        if user_agent:
            return "useragent:%s" % user_agent
        return None

    def _update_scaling_params(self):
        # type: () -> Optional[ScaleProvider]
        if self._device_pixel_ratio != self._UNKNOWN_DEVICE_PIXEL_RATIO:
            logger.debug("Device pixel ratio was already changed")
            return None

        logger.info("Trying to extract device pixel ratio...")
        try:
            device_pixel_ratio = image_utils.get_device_pixel_ratio(self._driver)
        except Exception as e:
            logger.info(
                "Failed to extract device pixel ratio! Using default. Error %s " % e
            )
            device_pixel_ratio = self._DEFAULT_DEVICE_PIXEL_RATIO
        logger.info("Device pixel ratio: {}".format(device_pixel_ratio))

        logger.info("Setting scale provider...")
        try:
            scale_provider = ContextBasedScaleProvider(
                top_level_context_entire_size=self._driver.get_entire_page_size(),
                viewport_size=self._get_viewport_size(),
                device_pixel_ratio=device_pixel_ratio,
                # always False as in Java version
                is_mobile_device=False,
            )  # type: ScaleProvider
        except Exception:
            # This can happen in Appium for example.
            logger.info("Failed to set ContextBasedScaleProvider.")
            logger.info("Using FixedScaleProvider instead...")
            scale_provider = FixedScaleProvider(1 / device_pixel_ratio)
        logger.info("Done!")
        return scale_provider

    @contextlib.contextmanager
    def _hide_scrollbars_if_needed(self):
        if self.hide_scrollbars:
            original_overflow = self._driver.hide_scrollbars()
        yield
        if self.hide_scrollbars:
            self._driver.set_overflow(original_overflow)

    def _try_capture_dom(self):
        try:
            dom_json = dom_capture.get_full_window_dom(self._driver)
            return dom_json
        except Exception as e:
            logger.warning(
                "Exception raising during capturing DOM Json. Passing...\n "
                "Got next error: {}".format(str(e))
            )
            return None

    def _get_screenshot(self):
        scale_provider = self._update_scaling_params()

        if self._screenshot_type == ScreenshotType.ENTIRE_ELEMENT_SCREENSHOT:
            self._last_screenshot = self._entire_element_screenshot(scale_provider)

        elif self._screenshot_type == ScreenshotType.FULLPAGE_SCREENSHOT:
            self._last_screenshot = self._full_page_screenshot(scale_provider)

        elif self._screenshot_type == ScreenshotType.VIEWPORT_SCREENSHOT:
            self._last_screenshot = self._viewport_screenshot(scale_provider)

        elif self._screenshot_type == ScreenshotType.REGION_OR_ELEMENT_SCREENSHOT:
            self._last_screenshot = self._region_or_screenshot(scale_provider)

        else:
            raise EyesError("No proper ScreenshotType obtained")
        return self._last_screenshot

    def get_screenshot(self, hide_scrollbars_called=False):
        if hide_scrollbars_called:
            return self._get_screenshot()
        else:
            with self._hide_scrollbars_if_needed():
                return self._get_screenshot()

    def _entire_element_screenshot(self, scale_provider):
        # type: (ScaleProvider) -> EyesWebDriverScreenshot
        logger.info("Entire element screenshot requested")
        screenshot = self._driver.get_stitched_screenshot(
            self._region_to_check, self._seconds_to_wait_screenshot, scale_provider
        )
        return EyesWebDriverScreenshot.create_from_image(screenshot, self._driver)

    def _region_or_screenshot(self, scale_provider):
        # type: (ScaleProvider) -> EyesWebDriverScreenshot
        logger.info("Not entire element screenshot requested")
        screenshot = self._viewport_screenshot(scale_provider)
        region = screenshot.get_element_region_in_frame_viewport(self._region_to_check)
        screenshot = screenshot.get_sub_screenshot_by_region(region)
        return screenshot

    def _full_page_screenshot(self, scale_provider):
        # type: (ScaleProvider) -> EyesWebDriverScreenshot
        logger.info("Full page screenshot requested")
        screenshot = self._driver.get_full_page_screenshot(
            self._seconds_to_wait_screenshot, scale_provider
        )
        return EyesWebDriverScreenshot.create_from_image(screenshot, self._driver)

    def _viewport_screenshot(self, scale_provider):
        # type: (ScaleProvider) -> EyesWebDriverScreenshot
        logger.info("Viewport screenshot requested")

        self._driver._wait_before_screenshot(self._seconds_to_wait_screenshot)
        if not self._driver.is_mobile_device():
            image64 = self._driver.get_screesnhot_as_base64_from_main_frame()
        else:
            image64 = self._driver.get_screenshot_as_base64()

        image = image_utils.image_from_bytes(base64.b64decode(image64))
        scale_provider.update_scale_ratio(image.width)
        pixel_ratio = 1 / scale_provider.scale_ratio
        if pixel_ratio != 1.0:
            image = image_utils.scale_image(image, 1.0 / pixel_ratio)
        return EyesWebDriverScreenshot.create_from_image(
            image, self._driver
        ).get_viewport_screenshot()

    def _ensure_viewport_size(self):
        if self._viewport_size is None:
            self._viewport_size = self._driver.get_default_content_viewport_size()
            if not eyes_selenium_utils.is_mobile_device(self._driver):
                eyes_selenium_utils.set_viewport_size(self._driver, self._viewport_size)

    def open(self, driver, app_name, test_name, viewport_size=None):
        # type: (AnyWebDriver, Text, Text, Optional[ViewPort]) -> EyesWebDriver
        if self.is_disabled:
            logger.debug("open(): ignored (disabled)")
            return driver

        if isinstance(driver, EyesWebDriver):
            # If the driver is an EyesWebDriver (as might be the case when tests are ran
            # consecutively using the same driver object)
            self._driver = driver
        else:
            if not isinstance(driver, RemoteWebDriver):
                logger.info(
                    "WARNING: driver is not a RemoteWebDriver (class: {0})".format(
                        driver.__class__
                    )
                )
            self._driver = EyesWebDriver(driver, self, self._stitch_mode)

        if viewport_size is not None:
            self._viewport_size = viewport_size
            eyes_selenium_utils.set_viewport_size(self._driver, viewport_size)

        self._ensure_viewport_size()
        self._open_base(app_name, test_name, viewport_size)

        return self._driver

    def check_window(self, tag=None, match_timeout=-1, target=None):
        # type: (Optional[Text], int, Optional[Target]) -> None
        """
        Takes a snapshot from the browser using the web driver and matches
        it with the expected output.

        :param tag: Description of the visual validation checkpoint.
        :param match_timeout: Timeout for the visual validation checkpoint (
                              milliseconds).
        :param target: The target for the check_window call
        :return: None
        """
        logger.info("check_window('%s')" % tag)
        if target is None:
            target = Target()

        self._screenshot_type = self._obtain_screenshot_type(
            is_element=False,
            inside_a_frame=bool(self._driver.frame_chain),
            stitch_content=False,
            force_fullpage=self.force_full_page_screenshot,
        )
        self._check_window_base(tag, match_timeout, target)

    def check_region(
        self, region, tag=None, match_timeout=-1, target=None, stitch_content=False
    ):
        # type: (Region, Optional[Text], int, Optional[Target], bool) -> None
        """
        Takes a snapshot of the given region from the browser using the web driver
        and matches it with the expected output. If the current context is a frame,
        the region is offsetted relative to the frame.

        :param region: The region which will be visually validated. The coordinates are
                       relative to the viewport of the current frame.
        :param tag: Description of the visual validation checkpoint.
        :param match_timeout: Timeout for the visual validation checkpoint
                              (milliseconds).
        :param target: The target for the check_window call
        :return: None
        """
        logger.info("check_region([%s], '%s')" % (region, tag))
        if region.is_empty:
            raise EyesError("region cannot be empty!")
        if target is None:
            target = Target()

        self._screenshot_type = self._obtain_screenshot_type(
            is_element=False,
            inside_a_frame=bool(self._driver.frame_chain),
            stitch_content=stitch_content,
            force_fullpage=self.force_full_page_screenshot,
            is_region=True,
        )
        self._region_to_check = region
        self._check_window_base(tag, match_timeout, target)

    def check_region_by_element(
        self, element, tag=None, match_timeout=-1, target=None, stitch_content=False
    ):
        # type: (AnyWebElement, Optional[Text], int, Optional[Target], bool) -> None
        """
        Takes a snapshot of the region of the given element from the browser using
        the web driver and matches it with the expected output.

        :param element: The element which region will be visually validated.
        :param tag: Description of the visual validation checkpoint.
        :param match_timeout: Timeout for the visual validation checkpoint
                              (milliseconds).
        :param target: The target for the check_window call
        :return: None
        """
        logger.info("check_region_by_element('%s')" % tag)
        if target is None:
            target = Target()

        self._screenshot_type = self._obtain_screenshot_type(
            is_element=True,
            inside_a_frame=bool(self._driver.frame_chain),
            stitch_content=stitch_content,
            force_fullpage=self.force_full_page_screenshot,
        )

        self._element_position_provider = ElementPositionProvider(self._driver, element)

        origin_overflow = element.get_overflow()
        element.set_overflow("hidden")

        element_region = self._get_element_region(element)
        self._region_to_check = element_region
        self._check_window_base(tag, match_timeout, target)
        self._element_position_provider = None

        if origin_overflow:
            element.set_overflow(origin_overflow)

    def _get_element_region(self, element):
        #  We use a smaller size than the actual screenshot size in order to
        #  eliminate duplication of bottom scroll bars,
        #  as well as footer-like elements with fixed position.
        pl = element.location
        # TODO: add correct values for Safari
        # in the safari browser the returned size has absolute value but not relative as
        # in other browsers
        element_width = element.get_client_width()
        element_height = element.get_client_height()
        border_left_width = element.get_computed_style_int("border-left-width")
        border_top_width = element.get_computed_style_int("border-top-width")
        element_region = Region(
            pl["x"] + border_left_width,
            pl["y"] + border_top_width,
            element_width,
            element_height,
        )
        return element_region

    def check_region_by_selector(
        self, by, value, tag=None, match_timeout=-1, target=None, stitch_content=False
    ):
        # type: (Text, Text, Optional[Text], int, Optional[Target], bool) -> None
        """
        Takes a snapshot of the region of the element found by calling find_element
        (by, value) and matches it with the expected output.

        :param by: The way by which an element to be validated should be found
                   (e.g., By.ID).
        :param value: The value identifying the element using the "by" type.
        :param tag: Description of the visual validation checkpoint.
        :param match_timeout: Timeout for the visual validation checkpoint
                              (milliseconds).
        :param target: The target for the check_window call
        :return: None
        """
        logger.debug("calling 'check_region_by_selector'...")
        # hack: prevent stale element exception by saving viewport value
        # before catching element
        self._driver.get_default_content_viewport_size()
        self.check_region_by_element(
            self._driver.find_element(by, value),
            tag,
            match_timeout,
            target,
            stitch_content,
        )

    def check_region_in_frame_by_selector(
        self,
        frame_reference,  # type: FrameReference
        by,  # type: Text
        value,  # type: Text
        tag=None,  # type: Optional[Text]
        match_timeout=-1,  # type: int
        target=None,  # type: Optional[Target]
        stitch_content=False,  # type: bool
    ):
        # type: (...) -> None
        """
        Checks a region within a frame, and returns to the current frame.

        :param frame_reference: A reference to the frame in which the region
                                should be checked.
        :param by: The way by which an element to be validated should be found (By.ID).
        :param value: The value identifying the element using the "by" type.
        :param tag: Description of the visual validation checkpoint.
        :param match_timeout: Timeout for the visual validation checkpoint
                              (milliseconds).
        :param target: The target for the check_window call
        :return: None
        """
        # TODO: remove this disable
        if self.is_disabled:
            logger.info("check_region_in_frame_by_selector(): ignored (disabled)")
            return
        logger.info("check_region_in_frame_by_selector('%s')" % tag)

        # Switching to the relevant frame
        with self._driver.switch_to.frame_and_back(frame_reference):
            logger.debug("calling 'check_region_by_selector'...")
            self.check_region_by_selector(
                by, value, tag, match_timeout, target, stitch_content
            )

    def add_mouse_trigger_by_element(self, action, element):
        # type: (Text, AnyWebElement) -> None
        """
        Adds a mouse trigger.

        :param action: Mouse action (click, double click etc.)
        :param element: The element on which the action was performed.
        """
        if self.is_disabled:
            logger.debug("add_mouse_trigger: Ignoring %s (disabled)" % action)
            return
        # Triggers are activated on the last checked window.
        if self._last_screenshot is None:
            logger.debug("add_mouse_trigger: Ignoring %s (no screenshot)" % action)
            return
        if not self._driver.frame_chain == self._last_screenshot.frame_chain:
            logger.debug("add_mouse_trigger: Ignoring %s (different frame)" % action)
            return
        control = self._last_screenshot.get_intersected_region_by_element(element)
        # Making sure the trigger is within the last screenshot bounds
        if control.is_empty:
            logger.debug("add_mouse_trigger: Ignoring %s (out of bounds)" % action)
            return
        cursor = control.middle_offset
        trigger = MouseTrigger(action, control, cursor)
        self._user_inputs.append(trigger)
        logger.info("add_mouse_trigger: Added %s" % trigger)

    def add_text_trigger_by_element(self, element, text):
        # type: (AnyWebElement, Text) -> None
        """
        Adds a text trigger.

        :param element: The element to which the text was sent.
        :param text: The trigger's text.
        """
        if self.is_disabled:
            logger.debug("add_text_trigger: Ignoring '%s' (disabled)" % text)
            return
        # Triggers are activated on the last checked window.
        if self._last_screenshot is None:
            logger.debug("add_text_trigger: Ignoring '%s' (no screenshot)" % text)
            return
        if not self._driver.frame_chain == self._last_screenshot.frame_chain:
            logger.debug("add_text_trigger: Ignoring %s (different frame)" % text)
            return
        control = self._last_screenshot.get_intersected_region_by_element(element)
        # Making sure the trigger is within the last screenshot bounds
        if control.is_empty:
            logger.debug("add_text_trigger: Ignoring %s (out of bounds)" % text)
            return
        trigger = TextTrigger(control, text)
        self._user_inputs.append(trigger)
        logger.info("add_text_trigger: Added %s" % trigger)
