import bdDetect
import typing
import braille

if typing.TYPE_CHECKING:
	from ...lib import detection
else:
	import addonHandler
	addon: addonHandler.Addon = addonHandler.getCodeAddon()
	detection = addon.loadModule("lib.detection")


class MonkeyPatcher:

	@staticmethod
	def _bgScan(
			self: bdDetect.Detector,
			detectUsb: bool,
			detectBluetooth: bool,
			limitToDevices: typing.Optional[typing.List[str]]
	):
		self._stopEvent.clear()
		for driver, match in detection.bgScanRD(limitToDevices=limitToDevices):
			if self._stopEvent.isSet():
				return
			if limitToDevices and driver not in limitToDevices:
				continue
			if braille.handler.setDisplayByName(driver, detected=match):
				return
		bdDetect.Detector._bgScan._origin(self, detectUsb, detectBluetooth, limitToDevices)

	def patchBdDetect(self):
		self._bgScan._origin = bdDetect.Detector._bgScan
		bdDetect.Detector._bgScan = self._bgScan

	def unpatchBdDetect(self):
		bdDetect.Detector._bgScan = self._bgScan._origin
		del self._bgScan._origin

	def __init__(self):
		self.patchBdDetect()

	def __del__(self):
		self.unpatchBdDetect()